"""A11 review curator and review storage (Step 08; docs/04 first-person source reviews; D27, D28, D53).

The model proposes first-person reviews from single sources; the backend decides what a moderator sees.
Sources offered: comments, forum posts, portal user reviews (one record per review, D68), and the speech of videos
and shorts, when their evidence is eligible, their family's current policy allows quotation and their author is not a
broker or the developer. Blog posts are not offered (D68: on these projects they are brokers' and builders' writing).
The model sees each source's platform and the reviewer's role as the platform badges it (never a name).
Web pages kept as `forum_thread` mix the page author with commenters in one text, so no span of them can be credited
to one person; they are left out until a connector stores posts one by one. On-screen text and frames are not
anyone's spoken or written words and are left out too.

The model sees handles (s1, e1, ...), never IDs. The backend then:
- drops a review whose spans are invented or belong to another source than the one it names;
- checks the words against the original spans, in order: `verbatim` must equal them (spacing aside),
  `punctuation_normalised` must keep every word, `shortened` may only leave out whole sentences; `translated` is
  only from a language other than English and may only state numbers the original or its kept translation states;
  the moderator sees the original beside every translation;
- drops reviews holding a phone number or e-mail address, broker or developer perspectives, and over-long text;
- sets the credit line (`speaker_label`) from the perspective and source kind, and the construction-status flags
  (D27) from the perspective and the status in force on the source's date; a flagged review cannot be approved.
Reviews get stable IDs from their source and spans; a changed rendering is a new pending revision.
"""

from __future__ import annotations

import hashlib
import json
import re
import time
import unicodedata
from collections import defaultdict
from typing import Any

from pymongo.database import Database

from app import audit
from app.agents import consistency
from app.agents.common import Handles, cached_output, keep_output, numbers_in, record_run, stable_id, version_digest
from app.agents.consistency import consistency_flags
from app.agents.gateway import GatewayResult, ModelGateway
from app.config import REPO_ROOT
from app.contracts import ContractStore, to_view
from app.db import utcnow
from app.evidence.eligibility import eligibility, eligible_filter
from app.evidence.retrieval import _translation_of
from app.sources import policies

AGENT_ID = "A11_review_curator"
PROMPT_VERSION = "a11_review_curator.1.1"  # 1.1: portal reviews, platform and badge, sales pitches (D68)
SCHEMA_REF = "agents.schema.json#/$defs/ReviewCandidates"
SCHEMA_VERSION = "1.1.0"
PROMPT_PATH = REPO_ROOT / "prompts" / f"{PROMPT_VERSION}.md"
ROLE = "light"  # D53: Claude Haiku 5.5 for curation; every word is checked by the backend
MAX_TASK_CHARS = 9000
# At most this many sources per task, and room for every one of them to be a review: 36 comments in one task cut
# the answer off at 4,000 tokens in the first live run (14 Oct 2026). A task still cut off is split in two.
MAX_TASK_SOURCES = 12
MAX_OUTPUT_TOKENS = 10000
MAX_REVIEW_CHARS = 1200
MAX_NOTE_CHARS = 300
OPEN_STATUSES = ("pending", "changes_requested")

REVIEW_KINDS = {"comment", "forum_post", "user_review", "video", "short"}
SPOKEN_KINDS = {"video", "short"}
EXCLUDED_ROLES = {"broker", "developer_official"}
NOT_A_REVIEW = {"broker_or_developer", "official_record"}
SPEAKER = {
    "resident_experience": "a_resident",
    "owner_awaiting_possession": "an_owner_awaiting_possession",
    "site_visit": "a_site_visitor",
    "prospective_buyer": "a_prospective_buyer",
}
SPEAKER_BY_KIND = {"comment": "a_viewer", "video": "a_video_creator", "short": "a_video_creator"}
SPEAKER_BY_ROLE = {"owner": "an_owner", "resident": "a_resident", "prospective_buyer": "a_prospective_buyer"}
VIDEO_PLATFORMS = {"youtube_data_api", "spoken_video_transcripts", "instagram_public"}
PHONE = re.compile(r"(?<!\d)(?:\+?91[\s-]?)?[6-9]\d{4}[\s-]?\d{5}(?!\d)")
EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")
SENTENCE_END = re.compile(r"(?<=[.!?।|])\s+|\n+")


def _ref(evidence: dict[str, Any]) -> dict[str, Any]:
    return {"id": evidence["id"], "revision": evidence["revision"]}


def _source_key(evidence: dict[str, Any]) -> str:
    return f"{evidence['source']['id']}@{evidence['source']['revision']}"


def _position(evidence: dict[str, Any]) -> int:
    anchor = evidence["anchor"]
    return int(anchor["start_ms"] if anchor["kind"] == "time" else anchor["start"])


def _quotable(db: Database[dict[str, Any]], ref: dict[str, Any], cache: dict[str, bool]) -> bool:
    if ref["family"] not in cache:
        policy = policies.current(db, ref["family"])
        cache[ref["family"]] = bool(policy and policy["quotation_allowed"])
    return cache[ref["family"]]


def offered_sources(db: Database[dict[str, Any]], project_id: str) -> dict[str, dict[str, Any]]:
    """Source key -> {source, spans}: the project's sources whose eligible spans A11 may quote."""
    quotable: dict[str, bool] = {}
    out: dict[str, dict[str, Any]] = {}
    sources: dict[str, dict[str, Any] | None] = {}
    query = {**eligible_filter(db, project_id), "translation_of": None}
    for evidence in db["ai_evidence"].find(query).sort("_id", 1):
        key = _source_key(evidence)
        if key not in sources:
            sources[key] = db["ai_sources"].find_one({"_id": key})
        source = sources[key]
        if source is None or source["source_kind"] not in REVIEW_KINDS:
            continue
        if ((source.get("author") or {}).get("role")) in EXCLUDED_ROLES:
            continue
        spoken = source["source_kind"] in SPOKEN_KINDS
        if (spoken and evidence["modality"] != "speech") or (not spoken and evidence["modality"] != "text"):
            continue
        if not _quotable(db, evidence["policy"], quotable) or not eligibility(db, evidence).eligible:
            continue
        out.setdefault(key, {"source": source, "spans": []})["spans"].append(evidence)
    for entry in out.values():
        entry["spans"].sort(key=_position)
    return out


BUCKETS = 16  # sources are packed within fixed buckets of their ID


def _bucket(key: str) -> int:
    return int(hashlib.sha256(key.encode()).hexdigest()[:8], 16) % BUCKETS


def build_tasks(db: Database[dict[str, Any]], project_id: str) -> list[dict[str, Any]]:
    """Sources packed into tasks of at most MAX_TASK_SOURCES and about MAX_TASK_CHARS; a long source is split, never
    mixed into another's spans. Sources are packed within fixed buckets of their ID, so a source added or withdrawn
    changes the tasks of its bucket only and every other task keeps its key and its cached answer (audit, 14 Oct
    2026: one new source moved every later task, and Continue paid for them again)."""
    tasks: list[dict[str, Any]] = []
    offered = sorted(offered_sources(db, project_id).items())
    for bucket in range(BUCKETS):
        chunk: list[tuple[dict[str, Any], list[dict[str, Any]]]] = []
        size = 0
        for _key, entry in (item for item in offered if _bucket(item[0]) == bucket):
            spans: list[dict[str, Any]] = []
            for evidence in entry["spans"]:
                length = len(evidence["excerpt_text"] or "") * (2 if evidence["modality"] == "speech" else 1)
                if (size + length > MAX_TASK_CHARS or len(chunk) >= MAX_TASK_SOURCES) and (chunk or spans):
                    if spans:
                        chunk.append((entry["source"], spans))
                    tasks.append(_task(project_id, chunk))
                    chunk, spans, size = [], [], 0
                spans.append(evidence)
                size += length
            if spans:
                chunk.append((entry["source"], spans))
        if chunk:
            tasks.append(_task(project_id, chunk))
    return tasks


def _task(project_id: str, chunk: list[tuple[dict[str, Any], list[dict[str, Any]]]]) -> dict[str, Any]:
    refs = sorted(f"{e['id']}@{e['revision']}" for _, spans in chunk for e in spans)
    parts = [PROMPT_VERSION, version_digest(PROMPT_PATH, ROLE), SCHEMA_VERSION, project_id, *refs]
    digest = hashlib.sha256("|".join(parts).encode()).hexdigest()
    return {
        "key": f"a11:{digest[:32]}",
        "project_id": project_id,
        "sources": [{"source": s, "spans": spans} for s, spans in chunk],
    }


def split_task(task: dict[str, Any]) -> list[dict[str, Any]]:
    """A task the model could not answer whole (cut off, invalid or refused), as two tasks: half its sources each, or,
    for one source, half its spans each. A single span cannot be split (empty list)."""
    sources = task["sources"]
    if len(sources) >= 2:
        half = len(sources) // 2
        parts = [[(s["source"], s["spans"]) for s in part] for part in (sources[:half], sources[half:])]
    elif sources and len(sources[0]["spans"]) >= 2:
        source, spans = sources[0]["source"], sources[0]["spans"]
        half = len(spans) // 2
        parts = [[(source, spans[:half])], [(source, spans[half:])]]
    else:
        return []
    return [_task(task["project_id"], part) for part in parts]


def _platform(source: dict[str, Any]) -> str:
    from app.content.build import platform_name  # the content builder's names (YouTube, MagicBricks, Reddit, ...)

    return platform_name(source.get("canonical_url"))


def render(
    db: Database[dict[str, Any]], project: dict[str, Any], task: dict[str, Any]
) -> tuple[str, dict[str, Handles]]:
    sources, spans = Handles("s"), Handles("e")
    header = {
        "project": project["project_name"],
        "also_called": project.get("alternate_names") or [],
        "locality": project.get("locality"),
        "city": project.get("city"),
        "developer": project.get("developer"),
    }
    lines = ["Project (trusted):", json.dumps(header, ensure_ascii=False), "", "Sources (untrusted quoted data):"]
    for entry in task["sources"]:
        source = entry["source"]
        published = (source.get("publication_date") or {}).get("value")
        author = source.get("author") or {}
        item: dict[str, Any] = {
            "id": sources.add(entry),
            "kind": source["source_kind"],
            "platform": _platform(source),
            "reviewer_badge": author.get("role") if author.get("role_basis") == "platform_badge" else None,
            "title": source.get("title") if source["source_kind"] in SPOKEN_KINDS else None,
            "published": str(published)[:10] if published else None,
            "spans": [],
        }
        for evidence in entry["spans"]:
            span: dict[str, Any] = {
                "id": spans.add(evidence),
                "language": evidence["language"],
                "text": evidence["excerpt_text"],
                "english_translation": _translation_of(db, evidence),
            }
            if evidence["anchor"]["kind"] == "time":
                span["at_seconds"] = evidence["anchor"]["start_ms"] // 1000
            item["spans"].append(span)
        lines.append(json.dumps(item, ensure_ascii=False))
    return "\n".join(lines), {"s": sources, "e": spans}


DASH = re.compile("[" + "".join(re.escape(c) for c in consistency.rules()["review_text"]["forbidden_characters"]) + "]")


def without_dashes(text: str) -> str:
    """Dashes between phrases become commas, hyphens inside words become spaces; every word is kept."""
    out = re.sub(r"\s*[\u2012-\u2015]\s*|\s+[-\u2010\u2011]+\s+", ", ", text)
    out = DASH.sub(" ", out)
    out = re.sub(r"\s+,", ",", out)
    out = re.sub(r",(\s*,)+", ",", out)
    return re.sub(r"[ \t]{2,}", " ", out).strip(" ,")


def _spaced(text: str) -> str:
    return " ".join(text.split())


def words(text: str) -> list[str]:
    """Words as written: runs of letters, marks and digits (Devanagari vowel signs stay inside their word)."""
    out: list[str] = []
    current: list[str] = []
    for ch in text:
        if ch.isspace() or unicodedata.category(ch)[0] in "PSZ":
            if current:
                out.append("".join(current))
                current = []
        else:
            current.append(ch)
    if current:
        out.append("".join(current))
    return out


def sentences(text: str) -> list[str]:
    return [s for s in (_spaced(p) for p in SENTENCE_END.split(text)) if s]


def rendering_problem(rendering: str, text: str, original: str, languages: list[str], translations: str) -> str | None:
    """Why the text is not an honest rendering of the original, or None."""
    if rendering == "verbatim":
        return None if _spaced(text) == _spaced(original) else "verbatim_changed"
    if rendering == "punctuation_normalised":
        return None if words(text) == words(original) else "words_changed"
    if rendering == "shortened":
        # whole sentences, compared word by word, so a shortened review may also have its dashes normalised (D28)
        kept, all_sentences = [words(x) for x in sentences(text)], [words(x) for x in sentences(original)]
        position = 0
        for sentence in kept:
            while position < len(all_sentences) and all_sentences[position] != sentence:
                position += 1
            if position == len(all_sentences):
                return "not_whole_sentences"
            position += 1
        return None if kept else "not_whole_sentences"
    if rendering == "translated":
        if all(lang == "en" or lang.startswith("en-") for lang in languages):
            return "translated_from_english"
        if numbers_in(text) - numbers_in(original + " " + translations):
            return "number_not_in_original"
        return None
    return "unknown_rendering"


def speaker_label(perspective: str, source_kind: str, source: dict[str, Any] | None = None) -> str | None:
    """Who the credit names: from what the author says (perspective), else the platform's badge, else the platform
    (a YouTube commenter is a viewer; someone on Reddit, Quora or a portal forum is a user)."""
    if perspective in SPEAKER:
        return SPEAKER[perspective]
    role = ((source or {}).get("author") or {}).get("role")
    if role in SPEAKER_BY_ROLE:
        return SPEAKER_BY_ROLE[role]
    if source is not None and source.get("connector_id") not in VIDEO_PLATFORMS:
        return "a_user" if source_kind in ("comment", "forum_post", "user_review") else SPEAKER_BY_KIND.get(source_kind)
    return SPEAKER_BY_KIND.get(source_kind)


def check(
    db: Database[dict[str, Any]],
    task: dict[str, Any],
    handles: dict[str, Handles],
    data: dict[str, Any],
    config: dict[str, Any],
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """Validated review drafts and the counts of what was dropped and why."""
    drops: dict[str, int] = defaultdict(int)
    drafts: list[dict[str, Any]] = []
    seen: set[tuple[str, ...]] = set()
    for index, item in enumerate(data.get("reviews", [])):
        found, _ = handles["s"].resolve([item.get("source_id", "")])
        cited, invented = handles["e"].resolve(item.get("evidence_ids") or [])
        if not found or invented:
            drops["invented_reference"] += 1
            continue
        entry = found[0]
        source = entry["source"]
        own = {e["id"] for e in entry["spans"]}
        if not cited or any(e["id"] not in own for e in cited):
            drops["spans_from_another_source"] += 1
            continue
        cited = sorted(cited, key=_position)
        perspective = item.get("perspective") or "unknown"
        if perspective in NOT_A_REVIEW:
            drops["not_a_first_person_review"] += 1
            continue
        label = speaker_label(perspective, source["source_kind"], source)
        if label is None:
            drops["speaker_unknown"] += 1
            continue
        text = (item.get("text") or "").strip()
        if not text or len(text) > MAX_REVIEW_CHARS:
            drops["empty_or_too_long"] += 1
            continue
        original = "\n".join(e["excerpt_text"] for e in cited)
        translations = " ".join(t for t in (_translation_of(db, e) for e in cited) if t)
        rendering = item.get("rendering") or ""
        problem = rendering_problem(rendering, text, original, [e["language"] for e in cited], translations)
        if problem:
            drops[problem] += 1
            continue
        if DASH.search(text):  # displayed reviews have no dashes or hyphens (product owner, 28 Sep 2026)
            text = without_dashes(text)
            rendering = "punctuation_normalised" if rendering == "verbatim" else rendering
            drops["dashes_normalised"] += 1
        if PHONE.search(text) or EMAIL.search(text):
            drops["personal_data"] += 1
            continue
        aspects = sorted(set(item.get("aspects") or []))
        polarity = item.get("polarity")
        if not aspects or polarity not in ("positive", "negative", "mixed"):
            drops["no_aspect_or_polarity"] += 1
            continue
        signature = (source["_id"], *(e["id"] for e in cited))
        if signature in seen:
            drops["duplicate"] += 1
            continue
        seen.add(signature)
        published = source.get("publication_date") or {
            "status": "unknown",
            "value": None,
            "precision": None,
            "basis": None,
        }
        link = db["ai_project_source_links"].find_one({"_id": cited[0]["link_id"]}, {"phase": 1}) or {}
        flags = consistency_flags(
            perspective,
            config.get("construction_status") or [],
            (link.get("phase") or {}).get("rera_id"),
            published.get("value"),
            aspects=aspects,
            polarity=polarity,
        )
        drafts.append(
            {
                "key": f"{task['key']}:{index}",
                "project_id": task["project_id"],
                "source": {"id": source["id"], "revision": source["revision"]},
                "link_id": cited[0]["link_id"],
                "evidence": [_ref(e) for e in cited],
                "source_kind": source["source_kind"],
                "perspective": perspective,
                "speaker_label": label,
                "polarity": polarity,
                "aspects": aspects,
                "original_text": original,
                "original_language": cited[0]["language"],
                "rendering": rendering,
                "text": text,
                "translation_note": " ".join((item.get("translation_note") or "").split())[:MAX_NOTE_CHARS] or None
                if rendering == "translated"
                else None,
                "published": published,
                "timestamp_ms": cited[0]["anchor"]["start_ms"] if source["source_kind"] in SPOKEN_KINDS else None,
                "consistency_flags": flags,
                "policy": cited[0]["policy"],
            }
        )
    return drafts, dict(drops)


def curate(
    db: Database[dict[str, Any]],
    gateway: ModelGateway,
    project: dict[str, Any],
    config: dict[str, Any],
    task: dict[str, Any],
    run_id: str | None,
    result: GatewayResult | None = None,
) -> dict[str, Any]:
    """Run (or reuse) one task. `result` is given when the call ran in a batch. Returns drafts and outcome."""
    started = time.monotonic()
    content, handles = render(db, project, task)
    data = cached_output(db, task["key"])
    if data is None and result is None:
        result = gateway.run(
            ROLE, SCHEMA_REF, PROMPT_PATH.read_text("utf-8"), content, max_tokens=MAX_OUTPUT_TOKENS, purpose=AGENT_ID
        )
    if data is None and result is not None and result.outcome == "completed" and result.data is not None:
        data = result.data
        keep_output(db, task["key"], AGENT_ID, data)
    inputs = [_ref(e) for entry in task["sources"] for e in entry["spans"]]
    if data is None:
        record_run(
            db,
            agent=AGENT_ID,
            task_key=task["key"],
            run_id=run_id,
            project_id=task["project_id"],
            prompt_version=PROMPT_VERSION,
            schema_version=SCHEMA_VERSION,
            result=result,
            input_refs=inputs,
            output_refs=[],
            outcome="failed",
            started=started,
        )
        return {"outcome": "failed", "drafts": [], "drops": {}, "error": result.error if result else None}
    drafts, drops = check(db, task, handles, data, config)
    outcome = data.get("outcome", "completed")
    record_run(
        db,
        agent=AGENT_ID,
        task_key=task["key"],
        run_id=run_id,
        project_id=task["project_id"],
        prompt_version=PROMPT_VERSION,
        schema_version=SCHEMA_VERSION,
        result=result,
        input_refs=inputs,
        output_refs=[],
        outcome=outcome,
        started=started,
    )
    return {"outcome": outcome, "drafts": drafts, "drops": drops, "error": None}


def review_id(draft: dict[str, Any]) -> str:
    return stable_id(
        "rex",
        draft["project_id"],
        f"{draft['source']['id']}@{draft['source']['revision']}",
        *(e["id"] for e in draft["evidence"]),
    )


def store_reviews(
    db: Database[dict[str, Any]], contracts: ContractStore, drafts: list[dict[str, Any]], run_id: str | None
) -> list[dict[str, Any]]:
    """Reviews for moderation. The same review from a rerun is not rewritten; a changed one is a new pending
    revision that supersedes the open earlier revision; a moderator's own revision is kept. The model's
    translation note is not part of the record: it stays in the task's kept output (ai_agent_outputs)."""
    now = utcnow()
    stored = []
    for draft in drafts:
        rid = review_id(draft)
        body = {k: v for k, v in draft.items() if k not in ("key", "translation_note")}
        body |= {
            "id": rid,
            "created_by": {
                "kind": "agent",
                "task_id": stable_id("tsk", draft["key"].rsplit(":", 1)[0], run_id or ""),
                "actor": None,
            },
            "lifecycle": "active",
        }
        latest = db["ai_review_excerpts"].find_one({"id": rid}, sort=[("revision", -1)])
        last_agent = db["ai_review_excerpts"].find_one({"id": rid, "created_by.kind": "agent"}, sort=[("revision", -1)])
        if (
            latest is not None
            and last_agent is not None
            and _same(last_agent, body)
            and latest["review_status"] != "superseded"  # retired by an earlier curation: proposed again, it returns
        ):
            stored.append({"id": rid, "revision": latest["revision"]})
            continue
        revision = (latest["revision"] + 1) if latest else 1
        doc = {
            "_id": f"{rid}@{revision}",
            **body,
            "revision": revision,
            "review_status": "pending",
            "supersedes": {"id": rid, "revision": latest["revision"]} if latest else None,
            "created_at": now,
        }
        problems = contracts.errors(to_view(doc, id_field=None) or {}, "evidence.schema.json#/$defs/ReviewExcerpt")
        if problems:
            raise ValueError(f"review {rid} does not meet the ReviewExcerpt contract: {problems[:3]}")
        db["ai_review_excerpts"].update_one({"_id": doc["_id"]}, {"$setOnInsert": doc}, upsert=True)
        if latest is not None:
            db["ai_review_excerpts"].update_many(
                {"id": rid, "revision": {"$lt": revision}, "review_status": {"$in": list(OPEN_STATUSES)}},
                {"$set": {"review_status": "superseded"}},
            )
        stored.append({"id": rid, "revision": revision})
    return stored


def retire_unproduced(
    db: Database[dict[str, Any]], project_id: str, sources: list[dict[str, Any]] | None, keep: list[dict[str, Any]]
) -> int:
    """Open agent reviews that this run did not propose again are superseded: of the given sources (those it fully
    curated), or of every source when the whole curation succeeded (`sources` None)."""
    kept = {r["id"] for r in keep}
    retired = 0
    query: dict[str, Any] = {
        "project_id": project_id,
        "created_by.kind": "agent",
        "review_status": {"$in": list(OPEN_STATUSES)},
    }
    if sources is not None:
        query["$or"] = [{"source.id": s["id"], "source.revision": s["revision"]} for s in sources] or [{"_id": None}]
    for review in db["ai_review_excerpts"].find(query, {"id": 1, "revision": 1}):
        if review["id"] in kept:
            continue
        db["ai_review_excerpts"].update_one(
            {"_id": review["_id"], "review_status": {"$in": list(OPEN_STATUSES)}},
            {"$set": {"review_status": "superseded"}},
        )
        audit.record(
            db,
            "reviews.superseded",
            "review_excerpt",
            review["id"],
            audit.SYSTEM_ACTOR,
            revision=review["revision"],
            details={"reason": "not proposed again by the newer curation of its source"},
        )
        retired += 1
    return retired


def _same(old: dict[str, Any], new: dict[str, Any]) -> bool:
    keys = (
        "evidence",
        "perspective",
        "speaker_label",
        "polarity",
        "aspects",
        "rendering",
        "text",
        "consistency_flags",
        "original_text",
    )
    return all(old.get(k) == new.get(k) for k in keys)
