"""Origin clusters (Step 07.3; OriginCluster contract; D50): copies of one origin count once.

Every source revision that carries evidence belongs to exactly one cluster; by default a cluster is the source on its
own. Sources are joined into one origin when:
- their whole texts are the same after normalisation (`exact_hash`);
- their whole texts are near-copies, with word-shingle Jaccard at least NEAR_JACCARD (`near_duplicate`);
- an evidence passage of at least PASSAGE_MIN_WORDS words reappears, with containment at least PASSAGE_CONTAINMENT,
  inside another source (`near_duplicate`): a copied or syndicated paragraph.
Texts shorter than MIN_WORDS are never joined: "Nice project" from three people is three opinions. Authors are never
compared across platforms. Clusters keep their IDs between runs; a changed membership is a new version, and every
change is audited. Evidence carries its source's cluster and version, so a claim counts distinct clusters.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from datetime import UTC, datetime
from typing import Any

from pymongo import MongoClient
from pymongo.client_session import ClientSession
from pymongo.database import Database

from app import audit
from app.db import run_in_transaction, utcnow
from app.evidence.similarity import (
    bands,
    jaccard,
    minhash,
    normalised_sha256,
    shingles,
    words,
)
from app.identity.intake import source_text
from app.ids import new_id
from app.jobs import queue
from app.observability import log_event

logger = logging.getLogger(__name__)
COLLECTION = "ai_origin_clusters"
MIN_WORDS = 12
NEAR_JACCARD = 0.8
PASSAGE_MIN_WORDS = 30
PASSAGE_CONTAINMENT = 0.9
EPOCH = datetime(1970, 1, 1, tzinfo=UTC)


def key_of(ref: dict[str, Any]) -> str:
    return f"{ref['id']}@{ref['revision']}"


def _text_of(db: Database[dict[str, Any]], source: dict[str, Any]) -> str | None:
    if source["source_kind"] in ("video", "short"):
        segments = (
            db["ai_media_segments"]
            .find({"source.id": source["id"], "source.revision": source["revision"]}, {"original_text_ref": 1})
            .sort("time.start_ms", 1)
        )
        refs = [s["original_text_ref"] for s in segments]
        payloads = {p["_id"]: p["text"] for p in db["ai_payloads"].find({"_id": {"$in": refs}}, {"text": 1})}
        transcript = " ".join(payloads[r] for r in refs if r in payloads)
        return transcript or None
    return source_text(db, source)


class _Union:
    def __init__(self, keys: list[str]) -> None:
        self.parent = {k: k for k in keys}
        self.method: dict[str, str] = {}

    def find(self, key: str) -> str:
        while self.parent[key] != key:
            self.parent[key] = self.parent[self.parent[key]]
            key = self.parent[key]
        return key

    def join(self, a: str, b: str, method: str) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra == rb:
            return  # already one origin; how it was joined does not change
        self.parent[rb] = ra
        near = "near_duplicate" in (method, self.method.get(ra), self.method.get(rb))
        self.method[ra] = "near_duplicate" if near else "exact_hash"


def group_sources(db: Database[dict[str, Any]]) -> tuple[dict[str, list[str]], dict[str, str], dict[str, Any]]:
    """Returns (groups by root key, method by root key, source docs by key) for every source with evidence."""
    keys = sorted({key_of(e["source"]) for e in db["ai_evidence"].find({}, {"source": 1})})
    docs = {s["_id"]: s for s in db["ai_sources"].find({"_id": {"$in": keys}}, {"author": 0})}
    keys = [k for k in keys if k in docs]
    union = _Union(keys)
    texts = {k: _text_of(db, docs[k]) for k in keys}
    sets = {k: shingles(t) for k, t in texts.items() if t and len(words(t)) >= MIN_WORDS}

    by_hash: dict[str, str] = {}
    for key in sorted(sets):
        digest = normalised_sha256(texts[key] or "")
        if digest in by_hash:
            union.join(by_hash[digest], key, "exact_hash")
        else:
            by_hash[digest] = key

    buckets: dict[tuple[int, tuple[int, ...]], list[str]] = defaultdict(list)
    for key in sorted(sets):
        for band in bands(minhash(sets[key])):
            buckets[band].append(key)
    checked: set[tuple[str, str]] = set()
    for members in buckets.values():
        for i, a in enumerate(members):
            for b in members[i + 1 :]:
                if (a, b) in checked:
                    continue
                checked.add((a, b))
                if union.find(a) != union.find(b) and jaccard(sets[a], sets[b]) >= NEAR_JACCARD:
                    union.join(a, b, "near_duplicate")

    index: dict[int, set[str]] = defaultdict(set)
    for key, items in sets.items():
        for item in items:
            index[item].add(key)
    for evidence in db["ai_evidence"].find({"excerpt_text": {"$type": "string"}}, {"source": 1, "excerpt_text": 1}):
        if len(words(evidence["excerpt_text"])) < PASSAGE_MIN_WORDS:
            continue
        own = key_of(evidence["source"])
        passage = shingles(evidence["excerpt_text"])
        counts: dict[str, int] = defaultdict(int)
        for item in passage:
            for other in index.get(item, ()):
                if other != own:
                    counts[other] += 1
        for other, shared in counts.items():  # shared / len(passage) is the passage's containment in `other`
            if own in docs and shared / len(passage) >= PASSAGE_CONTAINMENT:
                union.join(own, other, "near_duplicate")

    groups: dict[str, list[str]] = defaultdict(list)
    for key in keys:
        groups[union.find(key)].append(key)
    methods = {root: union.method.get(root, "exact_hash") for root in groups}
    return dict(groups), methods, docs


def _earliest(docs: dict[str, Any], members: list[str]) -> str:
    def when(key: str) -> datetime:
        date = docs[key].get("publication_date") or {}
        value = date.get("value") if date.get("status") != "unknown" else None
        return value if isinstance(value, datetime) else docs[key].get("collected_at") or EPOCH

    return min(sorted(members), key=when)


def cluster_origins(client: MongoClient[dict[str, Any]], db: Database[dict[str, Any]]) -> dict[str, int]:
    """Recompute groups, keep cluster IDs stable, write only what changed, and point evidence at its cluster."""
    groups, methods, docs = group_sources(db)
    existing = {c["_id"]: c for c in db[COLLECTION].find()}
    member_of = {key_of(m): cid for cid, c in existing.items() for m in c["members"]}
    now = utcnow()
    report = {"sources": len(docs), "clusters": len(groups), "created": 0, "changed": 0, "retired": 0, "joined": 0}
    claimed: set[str] = set()
    plans: list[dict[str, Any]] = []
    for root, members in sorted(groups.items(), key=lambda item: sorted(item[1])[0]):
        members = sorted(members)
        method = methods[root] if len(members) > 1 else "exact_hash"
        candidates = sorted(
            {member_of[m] for m in members if m in member_of and member_of[m] not in claimed},
            key=lambda cid: (existing[cid]["created_at"], cid),
        )
        refs = [{"id": docs[m]["id"], "revision": docs[m]["revision"]} for m in members]
        first = docs[_earliest(docs, members)]
        representative = {"id": first["id"], "revision": first["revision"]}
        if candidates:
            cid = candidates[0]
            claimed.add(cid)
            old = existing[cid]
            same = sorted(key_of(m) for m in old["members"]) == members and old["method"] == method
            doc = {**old, "members": refs, "representative": representative, "method": method}
            if not same:
                doc["version"] = old["version"] + 1
                report["changed"] += 1
        else:
            cid = new_id("cls")
            claimed.add(cid)
            doc = {
                "_id": cid,
                "version": 1,
                "members": refs,
                "representative": representative,
                "method": method,
                "created_at": now,
            }
            same = False
            report["created"] += 1
        report["joined"] += int(len(members) > 1)
        plans.append({"doc": doc, "write": not same, "members": members})
    retired = sorted(set(existing) - claimed)
    report["retired"] = len(retired)

    def write(session: ClientSession) -> None:
        for plan in plans:
            doc = plan["doc"]
            if plan["write"]:
                db[COLLECTION].replace_one({"_id": doc["_id"]}, doc, upsert=True, session=session)
            ref = {"id": doc["_id"], "version": doc["version"]}
            for member in plan["members"]:
                source_id, revision = member.rsplit("@", 1)
                db["ai_evidence"].update_many(
                    {"source.id": source_id, "source.revision": int(revision), "origin_cluster": {"$ne": ref}},
                    {"$set": {"origin_cluster": ref}},
                    session=session,
                )
        if retired:
            db[COLLECTION].delete_many({"_id": {"$in": retired}}, session=session)
        if report["created"] or report["changed"] or retired:
            audit.record(
                db,
                "origin_clusters.updated",
                "origin_clusters",
                "all",
                audit.SYSTEM_ACTOR,
                details={k: v for k, v in report.items()},
                session=session,
            )

    run_in_transaction(client, write)
    return report


def independent_origins(db: Database[dict[str, Any]], evidence_refs: list[dict[str, Any]]) -> list[str]:
    """Distinct origin clusters behind these evidence spans (a claim's independent-origin count is its length).
    Evidence not yet clustered counts as its own source."""
    ids = [r["id"] for r in evidence_refs]
    origins = set()
    for evidence in db["ai_evidence"].find({"id": {"$in": ids}}, {"source": 1, "origin_cluster": 1}):
        cluster = evidence.get("origin_cluster")
        origins.add(cluster["id"] if cluster else f"source:{key_of(evidence['source'])}")
    return sorted(origins)


KIND = "cluster_origins"


def start_clustering(db: Database[dict[str, Any]]) -> bool:
    """Scheduler: queue at most one clustering job per hour, and only when evidence is waiting for a cluster."""
    if not db["ai_evidence"].count_documents({"origin_cluster": None, "excerpt_text": {"$type": "string"}}, limit=1):
        return False
    _, created = queue.enqueue(db, KIND, f"{KIND}:{utcnow():%Y%m%d%H}", max_attempts=3)
    return created


def handle_cluster_origins(db: Database[dict[str, Any]], job: dict[str, Any], check: Any) -> str | None:
    """Worker handler: grouping is pure computation (about 15 s for 363 sources), so it runs as a job."""
    check()
    report = cluster_origins(db.client, db)
    log_event(logger, "origin clusters updated", **report)
    return None
