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
from app.embeddings.client import Embedder, EmbeddingUnavailable
from app.evidence.eligibility import eligibility, eligible_filter
from app.evidence.similarity import words

INDEX = "ai_evidence_search"
RETRIEVER = "keyword-v1"
RETRIEVERS = {"keyword": "keyword-v1", "vector": "vector-bge-m3-v1", "hybrid": "hybrid-rrf-v1"}
MODES = tuple(RETRIEVERS)
MAX_CANDIDATES = 200
MAX_RESULTS = 50
MAX_VECTOR_CANDIDATES = 2000  # newest first; similarity is computed in the API process, so it stays bounded
RRF_K = 60  # reciprocal rank fusion constant (Cormack et al., 2009)


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
                "embedding": None,  # filled by the embed_evidence job (D51)
                "embedding_model": None,
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
    embedder: Embedder | None = None,
    mode: str = "hybrid",
) -> dict[str, Any]:
    """mode: keyword, vector or hybrid. Without an embedder (or when it is down) the ranking is keyword-only and
    the result says why in `degraded`."""
    if mode not in MODES:
        raise ValueError(f"unknown retrieval mode {mode!r}")
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
    keyword: list[tuple[str, float]] = []
    similar: list[tuple[str, float]] = []
    degraded = None
    if terms and mode in ("keyword", "hybrid"):
        cursor = (
            db[INDEX]
            .find({**narrow, "$text": {"$search": terms}}, {"score": {"$meta": "textScore"}})
            .sort([("score", {"$meta": "textScore"}), ("_id", 1)])
            .limit(MAX_CANDIDATES)
        )
        keyword = [(c["_id"], round(c["score"], 4)) for c in cursor]
    if terms and mode in ("vector", "hybrid"):
        if embedder is None:
            degraded = "no embedder configured: keyword ranking only"
        else:
            try:
                similar = _nearest(db, narrow, embedder.embed([query.strip()])[0])
            except EmbeddingUnavailable as exc:
                degraded = f"embedder unavailable ({exc}): keyword ranking only"
        if degraded and not keyword:  # vector-only was asked for; give the keyword ranking rather than nothing
            cursor = (
                db[INDEX]
                .find({**narrow, "$text": {"$search": terms}}, {"score": {"$meta": "textScore"}})
                .sort([("score", {"$meta": "textScore"}), ("_id", 1)])
                .limit(MAX_CANDIDATES)
            )
            keyword = [(c["_id"], round(c["score"], 4)) for c in cursor]
    if not terms:
        cursor = db[INDEX].find(narrow, {"_id": 1}).sort([("published_at", -1), ("_id", 1)]).limit(MAX_CANDIDATES)
        keyword = [(c["_id"], 0.0) for c in cursor]
    ranked, used = _fuse(keyword, similar, mode if not degraded else "keyword")
    keyword_score, similarity = dict(keyword), dict(similar)
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
        items.append(
            {
                "evidence": evidence,
                "score": score,
                "keyword_score": keyword_score.get(evidence_id),
                "similarity": similarity.get(evidence_id),
                "flags": check.flags,
            }
        )
        if len(items) == limit:
            break
    return {
        "retriever": used,
        "degraded": degraded,
        "query_terms": terms,
        "candidates": len(ranked),
        "items": items,
        "elapsed_ms": round((time.perf_counter() - started) * 1000, 1),
    }


def _nearest(
    db: Database[dict[str, Any]], narrow: dict[str, Any], query_vector: list[float]
) -> list[tuple[str, float]]:
    """Cosine similarity (vectors are normalised) against at most MAX_VECTOR_CANDIDATES embedded entries."""
    import numpy as np

    rows = list(
        db[INDEX]
        .find({**narrow, "embedding": {"$type": "array"}}, {"embedding": 1})
        .sort([("published_at", -1), ("_id", 1)])
        .limit(MAX_VECTOR_CANDIDATES)
    )
    if not rows:
        return []
    matrix = np.asarray([r["embedding"] for r in rows], dtype=np.float32)
    scores = matrix @ np.asarray(query_vector, dtype=np.float32)
    order = np.argsort(-scores, kind="stable")[:MAX_CANDIDATES]
    return [(rows[i]["_id"], round(float(scores[i]), 4)) for i in order]


def _fuse(
    keyword: list[tuple[str, float]], similar: list[tuple[str, float]], mode: str
) -> tuple[list[tuple[str, float]], str]:
    """keyword or vector: that list as it is; hybrid: reciprocal rank fusion of both."""
    if mode == "keyword" or not similar:
        return keyword, RETRIEVERS["keyword"]
    if mode == "vector":
        return similar, RETRIEVERS["vector"]
    fused: dict[str, float] = {}
    for ranking in (keyword, similar):
        for rank, (evidence_id, _) in enumerate(ranking, 1):
            fused[evidence_id] = fused.get(evidence_id, 0.0) + 1.0 / (RRF_K + rank)
    ordered = sorted(fused.items(), key=lambda item: (-item[1], item[0]))
    return [(i, round(score, 5)) for i, score in ordered], RETRIEVERS["hybrid"]
