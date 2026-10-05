"""Read-only checks over the evidence layer (Step 07; `make verify-evidence`). Each row says what was checked, how
many records were looked at and which broke the rule. Nothing is changed."""

from __future__ import annotations

from typing import Any

from pymongo.database import Database

from app.evidence.anchors import anchor_problems
from app.evidence.retrieval import INDEX
from app.identity.intake import source_text
from app.sources.verify import _row

ERASED = ("withdrawn", "deleted", "expired")


def _key(ref: dict[str, Any]) -> str:
    return f"{ref['id']}@{ref['revision']}"


def verify_evidence(db: Database[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    evidence = list(db["ai_evidence"].find())
    sources = {s["_id"]: s for s in db["ai_sources"].find({}, {"author": 0})}
    links = {
        lk["_id"]: lk for lk in db["ai_project_source_links"].find({}, {"project_id": 1, "source": 1, "status": 1})
    }

    texts: dict[str, str | None] = {}
    segments: dict[str, list[dict[str, Any]]] = {}
    broken: list[str] = []
    for e in evidence:
        key = _key(e["source"])
        source = sources.get(key)
        if source is None:
            broken.append(e["_id"])
            continue
        media = source["source_kind"] in ("video", "short")
        if media and key not in segments:
            segments[key] = list(
                db["ai_media_segments"].find({"source.id": source["id"], "source.revision": source["revision"]})
            )
        if not media and key not in texts:
            texts[key] = source_text(db, source)
        if anchor_problems(db, e, texts.get(key), segments.get(key)):
            broken.append(e["_id"])
    rows.append(_row("every anchor and context re-derives its excerpt from the stored source", len(evidence), broken))

    broken = [
        e["_id"]
        for e in evidence
        if e["link_id"] not in links
        or links[e["link_id"]]["project_id"] != e["project_id"]
        or _key(links[e["link_id"]]["source"]) != _key(e["source"])
    ]
    rows.append(_row("evidence agrees with its link on project and source revision", len(evidence), broken))

    erased = [
        e for e in evidence if e["lifecycle"] in ERASED or sources.get(_key(e["source"]), {}).get("lifecycle") in ERASED
    ]
    broken = [
        e["_id"]
        for e in erased
        if e.get("excerpt_text") is not None and sources.get(_key(e["source"]), {}).get("payload_ref") is None
    ]
    rows.append(_row("erased evidence keeps no words", len(erased), broken))

    words = {e["_id"]: e.get("excerpt_text") for e in evidence}
    entries = list(db[INDEX].find({}, {"text": 1}))
    broken = [x["_id"] for x in entries if words.get(x["_id"]) is None or words[x["_id"]] != x["text"]]
    rows.append(_row("the search index holds only words the evidence still has", len(entries), broken))

    clusters = {c["_id"]: c for c in db["ai_origin_clusters"].find()}
    clustered = [e for e in evidence if e.get("origin_cluster")]
    broken = [
        e["_id"]
        for e in clustered
        if e["origin_cluster"]["id"] not in clusters
        or _key(e["source"]) not in {_key(m) for m in clusters[e["origin_cluster"]["id"]]["members"]}
    ]
    rows.append(_row("every origin-cluster reference contains the evidence's source", len(clustered), broken))

    by_key = {_key(e): e for e in evidence}
    claims = list(db["ai_claims"].find())
    broken = [
        c["_id"]
        for c in claims
        if any(
            _key(r) not in by_key or by_key[_key(r)]["project_id"] != c["project_id"]
            for r in c["supporting_evidence"] + c["contradicting_evidence"]
        )
    ]
    rows.append(_row("claims cite existing evidence revisions of their own project", len(claims), broken))

    claim_keys = {_key(c): c for c in claims}
    findings = list(db["ai_findings"].find())
    broken = [
        f["_id"]
        for f in findings
        if any(_key(r) not in claim_keys or claim_keys[_key(r)]["project_id"] != f["project_id"] for r in f["claims"])
    ]
    rows.append(_row("findings cite existing claim revisions of their own project", len(findings), broken))

    finding_keys = {_key(f) for f in findings}
    review_keys = {_key(r) for r in db["ai_review_excerpts"].find({}, {"id": 1, "revision": 1})}
    contents = list(db["ai_content_revisions"].find({}, {"manifest": 1}))
    broken = [
        c["_id"]
        for c in contents
        if any(_key(r) not in finding_keys for r in c["manifest"]["findings"])
        or any(_key(r) not in claim_keys for r in c["manifest"]["claims"])
        or any(_key(r) not in review_keys for r in c["manifest"]["reviews"])
        or any(_key(r) not in by_key for r in c["manifest"]["evidence"])
        or any(_key(r) not in sources for r in c["manifest"]["sources"])
        or any(lk not in links for lk in c["manifest"]["links"])
    ]
    rows.append(_row("every content manifest reference resolves", len(contents), broken))
    return rows
