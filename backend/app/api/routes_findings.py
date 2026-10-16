"""Findings and first-person reviews for moderation (Steps 08.6 and 09.4; journeys J06, J07; D28).

Lists show each revision with its exact claims or spans, the evidence behind them and whether it may be approved
now. Decisions name the exact revision; the actor comes from the session (app.workflows.decisions). Edits create new
revisions under the same evidence rules (app.workflows.revisions).
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, Depends, Query
from pymongo.database import Database

from app.agents.reviews import rendering_problem
from app.api.deps import Principal, contract_body, contracts_dep, db_dep, known_id, require
from app.api.routes_ops import decode_cursor, encode_cursor
from app.api.routes_sources import evidence_view
from app.contracts import ContractStore, to_view
from app.errors import ApiError
from app.identity.intake import source_text
from app.workflows.decisions import decide_finding, decide_review, evidence_for, finding_problems
from app.workflows.revisions import revise_finding, revise_review

router = APIRouter(prefix="/v1", tags=["findings"])
REVIEW_STATUSES = {"pending", "approved", "rejected", "changes_requested", "superseded"}
KINDS = {"pro", "con", "neutral"}
EVIDENCE_PER_VIEW = 50


def _decisions(db: Database[dict[str, Any]], target_type: str, record_id: str) -> list[dict[str, Any]]:
    rows = db["ai_review_decisions"].find({"target.type": target_type, "target.id": record_id}).sort("_id", 1)
    return [v for v in (to_view(r) for r in rows) if v is not None]


def _evidence_views(db: Database[dict[str, Any]], spans: list[dict[str, Any]]) -> list[dict[str, Any]]:
    views = []
    texts: dict[str, str | None] = {}
    for evidence in spans[:EVIDENCE_PER_VIEW]:
        key = f"{evidence['source']['id']}@{evidence['source']['revision']}"
        source = db["ai_sources"].find_one({"_id": key})
        if source is None:
            continue
        if key not in texts:
            texts[key] = source_text(db, source) if evidence["anchor"]["kind"] == "text" else None
        views.append(evidence_view(db, evidence, source, texts[key]))
    return views


def finding_view(db: Database[dict[str, Any]], finding: dict[str, Any]) -> dict[str, Any]:
    """FindingView: the revision, its exact claims and their evidence (supporting and contradicting), and whether it
    may be approved now."""
    claims = [db["ai_claims"].find_one({"id": c["id"], "revision": c["revision"]}) for c in finding["claims"]]
    present = [c for c in claims if c is not None]
    spans = evidence_for(db, [e for c in present for e in c["supporting_evidence"] + c["contradicting_evidence"]])
    problems = finding_problems(db, finding)
    return {
        "finding": to_view(finding, id_field=None),
        "claims": [to_view(c, id_field=None) for c in present],
        "evidence": _evidence_views(db, spans),
        "eligible": not problems,
        "ineligibility_reasons": problems,
        "decisions": _decisions(db, "finding", finding["id"]),
    }


def review_view(db: Database[dict[str, Any]], review: dict[str, Any]) -> dict[str, Any]:
    """ReviewExcerptView: the revision, the spans it shows, the source link and the backend's rendering check."""
    source = db["ai_sources"].find_one({"_id": f"{review['source']['id']}@{review['source']['revision']}"})
    if source is None:
        raise ApiError(404, "not_found", "The review's source revision is missing")
    if review["text"] is None or review["original_text"] is None:
        check = "mismatch"
    elif review["rendering"] == "translated":
        check = "needs_moderator"
    else:
        problem = rendering_problem(
            review["rendering"], review["text"], review["original_text"], [review["original_language"]], ""
        )
        check = "mismatch" if problem else "matches_original"
    return {
        "review": to_view(review, id_field=None),
        "evidence": _evidence_views(db, evidence_for(db, review["evidence"])),
        "source_url": source["canonical_url"],
        "rendering_check": check,
        "decisions": _decisions(db, "review_excerpt", review["id"]),
    }


def _page(
    db: Database[dict[str, Any]], collection: str, query: dict[str, Any], cursor: str | None, limit: int
) -> tuple[list[dict[str, Any]], str | None]:
    before = decode_cursor(cursor)
    if before:
        query["_id"] = {"$lt": before}
    rows = list(db[collection].find(query).sort("_id", -1).limit(limit + 1))
    more = len(rows) > limit
    rows = rows[:limit]
    return rows, encode_cursor(rows[-1]["_id"]) if more and rows else None


def _project(db: Database[dict[str, Any]], project_id: str) -> None:
    known_id(project_id, "prj")
    if db["projects"].find_one({"_id": project_id}, {"_id": 1}) is None:
        raise ApiError(404, "not_found", "No such project")


def _status_filter(review_status: str | None) -> dict[str, Any]:
    if review_status is None:
        return {"review_status": {"$ne": "superseded"}}
    if review_status not in REVIEW_STATUSES:
        raise ApiError(
            422,
            "validation_failed",
            "Unknown status",
            fields=[{"path": "review_status", "message": review_status[:50]}],
        )
    return {"review_status": review_status}


@router.get(
    "/projects/{project_id}/findings",
    operation_id="listFindings",
    summary="Findings with exact claims, conflicts and eligibility",
)
def list_findings(
    project_id: str,
    _: Principal = Depends(require("listFindings")),
    db: Database[dict[str, Any]] = Depends(db_dep),
    review_status: str | None = Query(default=None),
    kind: str | None = Query(default=None),
    aspect: str | None = Query(default=None),
    cursor: str | None = Query(default=None),
    limit: int = Query(default=25, ge=1, le=100),
) -> dict[str, Any]:
    _project(db, project_id)
    query: dict[str, Any] = {"project_id": project_id, **_status_filter(review_status)}
    if kind is not None:
        if kind not in KINDS:
            raise ApiError(422, "validation_failed", "Unknown kind", fields=[{"path": "kind", "message": kind[:50]}])
        query["kind"] = kind
    if aspect is not None:
        query["aspect"] = aspect
    rows, next_cursor = _page(db, "ai_findings", query, cursor, limit)
    return {"items": [finding_view(db, r) for r in rows], "next_cursor": next_cursor}


@router.post(
    "/findings/{finding_id}/decisions",
    operation_id="decideFinding",
    summary="Approve, reject or request changes on an exact finding revision",
)
def decide_finding_route(
    finding_id: str,
    body: Any = Body(...),
    principal: Principal = Depends(require("decideFinding")),
    db: Database[dict[str, Any]] = Depends(db_dep),
    contracts: ContractStore = Depends(contracts_dep),
) -> dict[str, Any]:
    known_id(finding_id, "fnd")
    request = contract_body(contracts, body, "api.schema.json#/$defs/FindingDecisionRequest")
    return decide_finding(db.client, db, contracts, finding_id, request, principal.actor)


@router.post(
    "/findings/{finding_id}/revisions",
    operation_id="reviseFinding",
    summary="Edit a finding as a new revision from the exact base revision",
    status_code=201,
)
def revise_finding_route(
    finding_id: str,
    body: Any = Body(...),
    principal: Principal = Depends(require("reviseFinding")),
    db: Database[dict[str, Any]] = Depends(db_dep),
    contracts: ContractStore = Depends(contracts_dep),
) -> dict[str, Any]:
    known_id(finding_id, "fnd")
    request = contract_body(contracts, body, "api.schema.json#/$defs/FindingRevisionRequest")
    return revise_finding(db.client, db, contracts, finding_id, request, principal.actor)


@router.get(
    "/projects/{project_id}/review-excerpts",
    operation_id="listReviewExcerpts",
    summary="First-person reviews from real posts, comments and videos, with original words, evidence and checks",
    tags=["reviews"],
)
def list_review_excerpts(
    project_id: str,
    _: Principal = Depends(require("listReviewExcerpts")),
    db: Database[dict[str, Any]] = Depends(db_dep),
    review_status: str | None = Query(default=None),
    aspect: str | None = Query(default=None),
    cursor: str | None = Query(default=None),
    limit: int = Query(default=25, ge=1, le=100),
) -> dict[str, Any]:
    _project(db, project_id)
    query: dict[str, Any] = {"project_id": project_id, **_status_filter(review_status)}
    if aspect:  # a category (D77)
        query["aspects"] = aspect
    rows, next_cursor = _page(db, "ai_review_excerpts", query, cursor, limit)
    return {"items": [review_view(db, r) for r in rows], "next_cursor": next_cursor}


@router.post(
    "/review-excerpts/{excerpt_id}/decisions",
    operation_id="decideReviewExcerpt",
    summary="Approve, reject or request changes on an exact review revision; flagged reviews cannot be approved",
    tags=["reviews"],
)
def decide_review_route(
    excerpt_id: str,
    body: Any = Body(...),
    principal: Principal = Depends(require("decideReviewExcerpt")),
    db: Database[dict[str, Any]] = Depends(db_dep),
    contracts: ContractStore = Depends(contracts_dep),
) -> dict[str, Any]:
    known_id(excerpt_id, "rex")
    request = contract_body(contracts, body, "api.schema.json#/$defs/ReviewExcerptDecisionRequest")
    return decide_review(db.client, db, contracts, excerpt_id, request, principal.actor)


@router.post(
    "/review-excerpts/{excerpt_id}/revisions",
    operation_id="reviseReviewExcerpt",
    summary="Choose other spans of the same source or fix a translation, as a new revision",
    status_code=201,
    tags=["reviews"],
)
def revise_review_route(
    excerpt_id: str,
    body: Any = Body(...),
    principal: Principal = Depends(require("reviseReviewExcerpt")),
    db: Database[dict[str, Any]] = Depends(db_dep),
    contracts: ContractStore = Depends(contracts_dep),
) -> dict[str, Any]:
    known_id(excerpt_id, "rex")
    request = contract_body(contracts, body, "api.schema.json#/$defs/ReviewExcerptRevisionRequest")
    return revise_review(db.client, db, contracts, excerpt_id, request, principal.actor)
