"""A05 claim extractor (Step 08.3; docs/04; D53): atomic aspect claims from a project's eligible evidence.

Tasks are per source: all of one source revision's eligible spans for the project (split when long), so a later
run with new evidence reuses the cached output of unchanged sources and pays only for new ones. The model sees
handles (e1, e2, ...), never IDs. The backend then:
- drops references to handles it did not give (invented references) and claims left without evidence;
- drops a claim whose numbers do not all appear in its cited evidence or that evidence's kept English translation
  (model memory cannot supply a project fact);
- requires `aspect_label` exactly for `other`;
- computes construction-status flags (D27) from the claim's perspective, phase and date;
- marks opinions and promotions `not_applicable` for verification and facts and allegations `unverified` until A06.
Drafts are returned to the workflow; claims are stored after verification (app.agents.verify).
"""

from __future__ import annotations

import hashlib
import json
import time
from collections import defaultdict
from datetime import UTC, date, datetime
from typing import Any

from pymongo.database import Database

from app.agents.common import Handles, cached_output, keep_output, numbers_in, record_run, stable_id
from app.agents.consistency import consistency_flags
from app.agents.gateway import GatewayResult, ModelGateway
from app.config import REPO_ROOT
from app.evidence.eligibility import eligibility, eligible_filter
from app.evidence.retrieval import _translation_of

AGENT_ID = "A05_claim_extractor"
PROMPT_VERSION = "a05_claim_extractor.1.0"
SCHEMA_REF = "agents.schema.json#/$defs/ClaimExtraction"
SCHEMA_VERSION = "1.1.0"
PROMPT_PATH = REPO_ROOT / "prompts" / f"{PROMPT_VERSION}.md"
ROLE = "light"  # D53: Claude Haiku 5.5 for bulk extraction; changed only on measured evaluation
MAX_TASK_CHARS = 9000
MAX_STATEMENT_CHARS = 400
MAX_OUTPUT_TOKENS = 4000


def _source_key(evidence: dict[str, Any]) -> str:
    return f"{evidence['source']['id']}@{evidence['source']['revision']}"


def build_tasks(db: Database[dict[str, Any]], project_id: str) -> list[dict[str, Any]]:
    """One task per source revision (split when its spans are long), over the project's eligible evidence."""
    by_source: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for evidence in db["ai_evidence"].find(eligible_filter(db, project_id)).sort([("source.id", 1), ("_id", 1)]):
        if eligibility(db, evidence).eligible:
            by_source[_source_key(evidence)].append(evidence)
    tasks = []
    for key in sorted(by_source):
        chunk: list[dict[str, Any]] = []
        size = 0
        for evidence in by_source[key]:
            length = len(evidence["excerpt_text"] or "")
            if chunk and size + length > MAX_TASK_CHARS:
                tasks.append(_task(project_id, chunk))
                chunk, size = [], 0
            chunk.append(evidence)
            size += length
        if chunk:
            tasks.append(_task(project_id, chunk))
    return tasks


def _task(project_id: str, evidence: list[dict[str, Any]]) -> dict[str, Any]:
    refs = sorted(f"{e['id']}@{e['revision']}" for e in evidence)
    digest = hashlib.sha256("|".join([PROMPT_VERSION, SCHEMA_VERSION, project_id, *refs]).encode()).hexdigest()
    return {"key": f"a05:{digest[:32]}", "project_id": project_id, "evidence": evidence}


def render(db: Database[dict[str, Any]], project: dict[str, Any], task: dict[str, Any]) -> tuple[str, Handles]:
    handles = Handles("e")
    header = {
        "project": project["project_name"],
        "also_called": project.get("alternate_names") or [],
        "locality": project.get("locality"),
        "city": project.get("city"),
        "developer": project.get("developer"),
        "phases": [r.get("registered_name") for r in project.get("rera_registrations", [])],
    }
    lines = ["Project (trusted):", json.dumps(header, ensure_ascii=False), "", "Evidence (untrusted quoted data):"]
    sources = {}
    for evidence in task["evidence"]:
        key = _source_key(evidence)
        if key not in sources:
            sources[key] = (
                db["ai_sources"].find_one({"_id": key}, {"source_kind": 1, "canonical_url": 1, "publication_date": 1})
                or {}
            )
        source = sources[key]
        published = (source.get("publication_date") or {}).get("value")
        translation = _translation_of(db, evidence)
        item = {
            "id": handles.add(evidence),
            "kind": source.get("source_kind"),
            "modality": evidence["modality"],
            "host": (source.get("canonical_url") or "").split("/")[2] if source.get("canonical_url") else None,
            "published": str(published)[:10] if published else None,
            "language": evidence["language"],
            "text": evidence["excerpt_text"],
            "english_translation": translation,
        }
        lines.append(json.dumps(item, ensure_ascii=False))
    return "\n".join(lines), handles


def check(
    db: Database[dict[str, Any]], task: dict[str, Any], handles: Handles, data: dict[str, Any], config: dict[str, Any]
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """Validated claim drafts and the counts of what was dropped and why."""
    drops: dict[str, int] = defaultdict(int)
    drafts = []
    for index, item in enumerate(data.get("claims", [])):
        cited, invented = handles.resolve(item.get("evidence_ids") or [])
        if invented:
            drops["invented_reference"] += len(invented)
        if not cited:
            drops["no_valid_evidence"] += 1
            continue
        statement = " ".join((item.get("statement") or "").split())[:MAX_STATEMENT_CHARS]
        if not statement:
            drops["empty_statement"] += 1
            continue
        sources_text = " ".join((e["excerpt_text"] or "") + " " + (_translation_of(db, e) or "") for e in cited)
        missing = numbers_in(statement) - numbers_in(sources_text)
        if missing:
            drops["number_not_in_evidence"] += 1
            continue
        if (item.get("aspect") == "other") != bool(item.get("aspect_label")):
            drops["aspect_label_mismatch"] += 1
            continue
        observed = _observed(item)
        source = db["ai_sources"].find_one({"_id": _source_key(cited[0])}, {"publication_date": 1}) or {}
        when = observed["value"] or ((source.get("publication_date") or {}).get("value"))
        link = db["ai_project_source_links"].find_one({"_id": cited[0]["link_id"]}, {"phase": 1}) or {}
        flags = consistency_flags(
            item["perspective"], config.get("construction_status") or [], (link.get("phase") or {}).get("rera_id"), when
        )
        drafts.append(
            {
                "key": f"{task['key']}:{index}",
                "project_id": task["project_id"],
                "aspect": item["aspect"],
                "aspect_label": item.get("aspect_label") if item["aspect"] == "other" else None,
                "claim_type": item["claim_type"],
                "polarity": item["polarity"],
                "perspective": item["perspective"],
                "consistency_flags": flags,
                "statement": statement,
                "observation_time": observed,
                "supporting_evidence": [{"id": e["id"], "revision": e["revision"]} for e in cited],
                "verification_status": "not_applicable"
                if item["claim_type"] in ("opinion", "promotion")
                else "unverified",
            }
        )
    return drafts, dict(drops)


def _observed(item: dict[str, Any]) -> dict[str, Any]:
    status = item.get("observation_date_status") or "unknown"
    raw = item.get("observation_date")
    try:
        day = date.fromisoformat(raw) if raw and status != "unknown" else None
    except ValueError:
        day = None
    if day is None or day > datetime.now(UTC).date():
        return {"status": "unknown", "value": None, "precision": None, "basis": None}
    return {
        "status": status,
        "value": datetime(day.year, day.month, day.day, tzinfo=UTC),
        "precision": "day",
        "basis": "text_mention",
    }


def extract(
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
    if data is None and result is not None:
        if result.outcome == "completed" and result.data is not None:
            data = result.data
            keep_output(db, task["key"], AGENT_ID, data)
    inputs = [{"id": e["id"], "revision": e["revision"]} for e in task["evidence"]]
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
        return {"outcome": "failed", "drafts": [], "drops": {}, "error": (result.error if result else None)}
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
        output_refs=[{"id": stable_id("clm", d["key"]), "revision": 1} for d in drafts],
        outcome=outcome,
        started=started,
    )
    return {"outcome": outcome, "drafts": drafts, "drops": drops, "error": None}


def task_content(db: Database[dict[str, Any]], project: dict[str, Any], task: dict[str, Any]) -> str:
    return render(db, project, task)[0]
