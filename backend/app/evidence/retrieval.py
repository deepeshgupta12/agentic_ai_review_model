"""Filtered evidence retrieval, keyword baseline (Step 07.4; D50).

Filters come first, ranking second:
1. eligibility (app.evidence.eligibility.eligible_filter): this project's accepted links, usable source revisions,
   policies that still allow AI use, words not erased;
2. the caller's filters: modality, language, publication dates, phase (RERA ID) and aspect (through claims);
3. MongoDB's text index ranks what is left, at most MAX_CANDIDATES, and the best `limit` (at most MAX_RESULTS) are
   checked once more with the full eligibility rule before they are returned.

The text index lives in `ai_evidence_search`, a derived collection: one entry per evidence span with its words and,
when A04 kept one, its English translation, so an English query can reach Hindi speech. It can be rebuilt at any
time; `sync_index` brings a project's entries up to date before each search, and erasing a source deletes its
entries at once (app.sources.lifecycle). Ranking is keyword-only (no stemming, no synonyms); an embedding ranker is
a measured addition, not part of this baseline.
"""

from __future__ import annotations

import time
from datetime import datetime
from typing import Any

from pymongo.database import Database

from app.db import utcnow
from app.evidence.eligibility import eligibility, eligible_filter
from app.evidence.similarity import words

INDEX = "ai_evidence_search"
RETRIEVER = "keyword-v1"
MAX_CANDIDATES = 200
MAX_RESULTS = 50


def _translation_of(db: Database[dict[str, Any]], evidence: dict[str, Any]) -> str | None:
    """The English translation A04 kept for a media segment, if any."""
    anchor = evidence["anchor"]
    if anchor.get("kind") != "time":
        return None
    segment = db["ai_media_segments"].find_one(
        {
            "source.id": evidence["source"]["id"],
            "source.revision": evidence["source"]["revision"],
            "time.start_ms": anchor["start_ms"],
            "time.end_ms": anchor["end_ms"],
            "modality": evidence["modality"],
        },
        {"translation": 1},
    )
    ref = ((segment or {}).get("translation") or {}).get("text_ref")
    payload = db["ai_payloads"].find_one({"_id": ref}, {"text": 1}) if ref else None
    return payload["text"] if payload else None


def sync_index(db: Database[dict[str, Any]], project_id: str | None = None) -> dict[str, int]:
    """Add entries for evidence that has words and no entry; drop entries whose evidence lost its words."""
    scope: dict[str, Any] = {"project_id": project_id} if project_id else {}
    have = set(db[INDEX].distinct("_id", scope))
    live = {
        e["_id"]
        for e in db["ai_evidence"].find(
            {**scope, "excerpt_text": {"$type": "string"}, "lifecycle": "active"}, {"_id": 1}
        )
    }
    stale = sorted(have - live)
    if stale:
        db[INDEX].delete_many({"_id": {"$in": stale}})
    missing = sorted(live - have)
    sources: dict[str, Any] = {}
    links: dict[str, Any] = {}
    for evidence in db["ai_evidence"].find({"_id": {"$in": missing}}):
        key = f"{evidence['source']['id']}@{evidence['source']['revision']}"
        if key not in sources:
            sources[key] = db["ai_sources"].find_one({"_id": key}, {"publication_date": 1}) or {}
        if evidence["link_id"] not in links:
            links[evidence["link_id"]] = (
                db["ai_project_source_links"].find_one({"_id": evidence["link_id"]}, {"phase": 1}) or {}
            )
        date = sources[key].get("publication_date") or {}
        db[INDEX].replace_one(
            {"_id": evidence["_id"]},
            {
                "_id": evidence["_id"],
                "evidence": {"id": evidence["id"], "revision": evidence["revision"]},
                "project_id": evidence["project_id"],
                "source": evidence["source"],
                "link_id": evidence["link_id"],
                "modality": evidence["modality"],
                "language": evidence["language"],
                "text": evidence["excerpt_text"],
                "translation": _translation_of(db, evidence),
                "published_at": date.get("value") if date.get("status") not in (None, "unknown") else None,
                "phase_rera_id": (links[evidence["link_id"]].get("phase") or {}).get("rera_id"),
                "indexed_at": utcnow(),
            },
            upsert=True,
        )
    return {"added": len(missing), "removed": len(stale)}


def remove_source(db: Database[dict[str, Any]], source_id: str, revision: int, session: Any = None) -> int:
    """Erasure: the index must not keep words the source no longer has."""
    return db[INDEX].delete_many({"source.id": source_id, "source.revision": revision}, session=session).deleted_count


def search(
    db: Database[dict[str, Any]],
    project_id: str,
    query: str = "",
    *,
    modalities: list[str] | None = None,
    languages: list[str] | None = None,
    published_from: datetime | None = None,
    published_to: datetime | None = None,
    phase_rera_id: str | None = None,
    aspects: list[str] | None = None,
    limit: int = 10,
) -> dict[str, Any]:
    started = time.perf_counter()
    limit = max(1, min(limit, MAX_RESULTS))
    sync_index(db, project_id)
    terms = " ".join(words(query))
    narrow: dict[str, Any] = {"project_id": project_id}
    if modalities:
        narrow["modality"] = {"$in": modalities}
    if languages:
        narrow["language"] = {"$in": languages}
    if published_from or published_to:
        narrow["published_at"] = {k: v for k, v in (("$gte", published_from), ("$lte", published_to)) if v is not None}
    if phase_rera_id:
        narrow["phase_rera_id"] = phase_rera_id
    if aspects:
        cited = set()
        for claim in db["ai_claims"].find(
            {"project_id": project_id, "aspect": {"$in": aspects}},
            {"supporting_evidence": 1, "contradicting_evidence": 1},
        ):
            cited |= {
                f"{r['id']}@{r['revision']}" for r in claim["supporting_evidence"] + claim["contradicting_evidence"]
            }
        narrow["_id"] = {"$in": sorted(cited)}
    if terms:
        cursor = (
            db[INDEX]
            .find({**narrow, "$text": {"$search": terms}}, {"score": {"$meta": "textScore"}})
            .sort([("score", {"$meta": "textScore"}), ("_id", 1)])
            .limit(MAX_CANDIDATES)
        )
    else:
        cursor = db[INDEX].find(narrow, {"_id": 1}).sort([("published_at", -1), ("_id", 1)]).limit(MAX_CANDIDATES)
    ranked = [(c["_id"], round(c.get("score", 0.0), 4)) for c in cursor]
    candidates = {
        e["_id"]: e
        for e in db["ai_evidence"].find({**eligible_filter(db, project_id), "_id": {"$in": [i for i, _ in ranked]}})
    }
    items = []
    for evidence_id, score in ranked:
        evidence = candidates.get(evidence_id)
        if evidence is None:
            continue  # filtered out as ineligible
        check = eligibility(db, evidence)
        if not check.eligible:
            continue
        items.append({"evidence": evidence, "score": score, "flags": check.flags})
        if len(items) == limit:
            break
    return {
        "retriever": RETRIEVER,
        "query_terms": terms,
        "candidates": len(ranked),
        "items": items,
        "elapsed_ms": round((time.perf_counter() - started) * 1000, 1),
    }
