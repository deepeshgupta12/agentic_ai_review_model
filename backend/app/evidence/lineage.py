"""Dependency lineage (Step 07.5; docs/02 item 2, docs/05; D50): source revision -> evidence -> claim -> finding ->
content revision, and evidence -> source review -> content revision.

Every reference carries an exact revision, so a lookup matches (id, revision) pairs, never IDs alone: a claim that
cites evidence revision 1 is not affected by a change to revision 2. `affected` starts from source revisions, links
or evidence and returns everything that depends on them, including translations of the evidence. Content revisions
come with their lifecycle; `open` marks the drafts and the revisions in review or approved, which a correction must
reach. The invalidation job (app.identity.invalidation) uses this to report and act on dependants, and the console
and publication checks reuse it.
"""

from __future__ import annotations

from typing import Any

from pymongo.client_session import ClientSession
from pymongo.database import Database

OPEN_CONTENT = ("draft", "final_review", "changes_requested", "approved")
LIVE_REVIEW = ("pending", "approved", "changes_requested")
Ref = tuple[str, int]


def _pairs(refs: list[dict[str, Any]]) -> set[Ref]:
    return {(r["id"], r["revision"]) for r in refs}


def _cites(doc_refs: list[dict[str, Any]], wanted: set[Ref]) -> bool:
    return bool(_pairs(doc_refs) & wanted)


def affected(
    db: Database[dict[str, Any]],
    *,
    sources: list[dict[str, Any]] | None = None,
    links: list[str] | None = None,
    evidence: list[dict[str, Any]] | None = None,
    session: ClientSession | None = None,
) -> dict[str, Any]:
    """Everything that depends on these source revisions ({id, revision}; revision None means every revision), links
    or evidence revisions. Lists hold {id, revision}; content holds {id, project_id, locale, revision, lifecycle,
    open}."""
    source_pairs: set[Ref] = set()
    source_ids_any: set[str] = set()
    for ref in sources or []:
        if ref.get("revision") is None:
            source_ids_any.add(ref["id"])
        else:
            source_pairs.add((ref["id"], ref["revision"]))
    link_ids = set(links or [])

    query: list[dict[str, Any]] = []
    if source_ids_any:
        query.append({"source.id": {"$in": sorted(source_ids_any)}})
    if source_pairs:
        query.append({"source.id": {"$in": sorted({i for i, _ in source_pairs})}})
    if link_ids:
        query.append({"link_id": {"$in": sorted(link_ids)}})
    wanted = _pairs(evidence or [])
    if wanted:
        query.append({"id": {"$in": sorted({i for i, _ in wanted})}})
    found: dict[Ref, dict[str, Any]] = {}
    if query:
        for doc in db["ai_evidence"].find(
            {"$or": query}, {"id": 1, "revision": 1, "source": 1, "link_id": 1}, session=session
        ):
            key = (doc["id"], doc["revision"])
            src = (doc["source"]["id"], doc["source"]["revision"])
            if (
                doc["source"]["id"] in source_ids_any
                or src in source_pairs
                or doc["link_id"] in link_ids
                or key in wanted
            ):
                found[key] = doc
                link_ids.add(doc["link_id"])  # a source's links are affected; a link never widens to its source
    frontier = set(found)
    while frontier:  # translations of affected evidence are affected too
        ids = sorted({i for i, _ in frontier})
        frontier = set()
        for doc in db["ai_evidence"].find(
            {"translation_of.id": {"$in": ids}},
            {"id": 1, "revision": 1, "translation_of": 1, "source": 1, "link_id": 1},
            session=session,
        ):
            original = (doc["translation_of"]["id"], doc["translation_of"]["revision"])
            key = (doc["id"], doc["revision"])
            if original in found and key not in found:
                found[key] = doc
                frontier.add(key)
    evidence_pairs = set(found)
    evidence_ids = sorted({i for i, _ in evidence_pairs})

    claims = (
        [
            (c["id"], c["revision"])
            for c in db["ai_claims"].find(
                {
                    "$or": [
                        {"supporting_evidence.id": {"$in": evidence_ids}},
                        {"contradicting_evidence.id": {"$in": evidence_ids}},
                    ]
                },
                {"id": 1, "revision": 1, "supporting_evidence": 1, "contradicting_evidence": 1},
                session=session,
            )
            if _cites(c["supporting_evidence"] + c["contradicting_evidence"], evidence_pairs)
        ]
        if evidence_ids
        else []
    )
    claim_pairs = set(claims)
    findings = (
        [
            (f["id"], f["revision"])
            for f in db["ai_findings"].find(
                {"claims.id": {"$in": sorted({i for i, _ in claim_pairs})}},
                {"id": 1, "revision": 1, "claims": 1},
                session=session,
            )
            if _cites(f["claims"], claim_pairs)
        ]
        if claim_pairs
        else []
    )
    finding_pairs = set(findings)
    reviews = (
        [
            (r["id"], r["revision"])
            for r in db["ai_review_excerpts"].find(
                {
                    "$or": [
                        {"evidence.id": {"$in": evidence_ids}},
                        {"source.id": {"$in": sorted({i for i, _ in source_pairs})}},
                    ]
                },
                {"id": 1, "revision": 1, "evidence": 1, "source": 1},
                session=session,
            )
            if _cites(r["evidence"], evidence_pairs) or (r["source"]["id"], r["source"]["revision"]) in source_pairs
        ]
        if (evidence_ids or source_pairs)
        else []
    )
    review_pairs = set(reviews)

    manifest_query: list[dict[str, Any]] = []
    for field, pairs in (
        ("manifest.findings.id", finding_pairs),
        ("manifest.claims.id", claim_pairs),
        ("manifest.reviews.id", review_pairs),
        ("manifest.evidence.id", evidence_pairs),
        ("manifest.sources.id", source_pairs),
    ):
        if pairs:
            manifest_query.append({field: {"$in": sorted({i for i, _ in pairs})}})
    if link_ids:
        manifest_query.append({"manifest.links": {"$in": sorted(link_ids)}})
    content = []
    if manifest_query:
        for c in db["ai_content_revisions"].find(
            {"$or": manifest_query},
            {"project_id": 1, "locale": 1, "revision": 1, "lifecycle": 1, "manifest": 1},
            session=session,
        ):
            m = c["manifest"]
            hit = (
                _cites(m["findings"], finding_pairs)
                or _cites(m["claims"], claim_pairs)
                or _cites(m["reviews"], review_pairs)
                or _cites(m["evidence"], evidence_pairs)
                or _cites(m["sources"], source_pairs)
                or bool(set(m["links"]) & link_ids)
            )
            if hit:
                content.append(
                    {
                        "id": c["_id"],
                        "project_id": c["project_id"],
                        "locale": c["locale"],
                        "revision": c["revision"],
                        "lifecycle": c["lifecycle"],
                        "open": c["lifecycle"] in OPEN_CONTENT,
                    }
                )

    def refs(pairs: set[Ref] | list[Ref]) -> list[dict[str, Any]]:
        return [{"id": i, "revision": r} for i, r in sorted(set(pairs))]

    return {
        "evidence": refs(evidence_pairs),
        "claims": refs(claims),
        "findings": refs(findings),
        "reviews": refs(reviews),
        "content_revisions": sorted(content, key=lambda c: (c["project_id"], c["locale"], c["revision"])),
    }


def counts(lineage: dict[str, Any]) -> dict[str, int]:
    return {
        "evidence": len(lineage["evidence"]),
        "claims": len(lineage["claims"]),
        "findings": len(lineage["findings"]),
        "reviews": len(lineage["reviews"]),
        "content_revisions": len(lineage["content_revisions"]),
        "open_content_revisions": sum(1 for c in lineage["content_revisions"] if c["open"]),
    }
