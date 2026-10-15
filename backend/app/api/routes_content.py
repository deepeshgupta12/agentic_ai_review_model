"""Page content revisions (Step 10; journeys J08-J10; docs/09 Content editor).

Generation continues the project's paused analysis with the moderator's exact selection (202: the `format` step
writes and checks the draft in the worker; no HTTP request waits for a model). An edit is checked and stored at once
(201). Final approval and the other decisions name the exact revision; the actor comes from the session.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, Depends, Header, Query, Response
from pymongo.database import Database

from app.api.deps import Principal, contract_body, contracts_dep, db_dep, known_id, require, settings_dep
from app.api.idempotency import HEADER, run_idempotent
from app.api.routes_ops import decode_cursor, encode_cursor
from app.config import Settings
from app.content import service
from app.contracts import ContractStore
from app.errors import ApiError
from app.workflows.analysis import request_resume

router = APIRouter(prefix="/v1", tags=["content"])
LIFECYCLES = {"draft", "final_review", "changes_requested", "approved", "rejected", "superseded", "withdrawn"}


def _project(db: Database[dict[str, Any]], project_id: str) -> None:
    known_id(project_id, "prj")
    if db["projects"].find_one({"_id": project_id}, {"_id": 1}) is None:
        raise ApiError(404, "not_found", "No such project")


@router.post(
    "/projects/{project_id}/content-revisions",
    operation_id="createContentRevision",
    summary="Generate page content from approved findings and reviews, or save an edit as a new revision",
    status_code=201,
)
def create_content_revision(
    project_id: str,
    response: Response,
    body: Any = Body(...),
    idempotency_key: str | None = Header(default=None, alias=HEADER),
    principal: Principal = Depends(require("createContentRevision")),
    db: Database[dict[str, Any]] = Depends(db_dep),
    contracts: ContractStore = Depends(contracts_dep),
    settings: Settings = Depends(settings_dep),
) -> dict[str, Any]:
    _project(db, project_id)
    request = contract_body(contracts, body, "api.schema.json#/$defs/ContentRevisionRequest")
    if request["mode"] == "generate":
        if not request["findings"] and not request["reviews"]:
            raise ApiError(
                422,
                "validation_failed",
                "Select at least one approved finding or review",
                fields=[{"path": "findings", "message": "nothing selected"}],
            )
        service.check_review_limits(db, settings, request["reviews"])
        response.status_code = 202
        return run_idempotent(
            db,
            operation_id="createContentRevision",
            user_id=principal.user_id,
            key=idempotency_key,
            body={"project_id": project_id, **request},
            compute=lambda: request_resume(db, project_id, request, principal.actor),
        )
    return run_idempotent(
        db,
        operation_id="createContentRevision",
        user_id=principal.user_id,
        key=idempotency_key,
        body={"project_id": project_id, **request},
        compute=lambda: service.save_edit(db, contracts, settings, project_id, request, principal.actor),
    )


@router.get(
    "/projects/{project_id}/content-revisions",
    operation_id="listContentRevisions",
    summary="Content revisions of a project, newest first, with their QA issues",
)
def list_content_revisions(
    project_id: str,
    _: Principal = Depends(require("listContentRevisions")),
    db: Database[dict[str, Any]] = Depends(db_dep),
    lifecycle: str | None = Query(default=None),
    cursor: str | None = Query(default=None),
    limit: int = Query(default=25, ge=1, le=100),
) -> dict[str, Any]:
    _project(db, project_id)
    query: dict[str, Any] = {"project_id": project_id}
    if lifecycle is not None:
        if lifecycle not in LIFECYCLES:
            raise ApiError(
                422, "validation_failed", "Unknown lifecycle", fields=[{"path": "lifecycle", "message": lifecycle[:50]}]
            )
        query["lifecycle"] = lifecycle
    before = decode_cursor(cursor)
    if before:
        if not before.isdigit():
            raise ApiError(
                422, "validation_failed", "Invalid cursor", fields=[{"path": "cursor", "message": "not a valid cursor"}]
            )
        query["revision"] = {"$lt": int(before)}
    rows = list(db[service.REVISIONS].find(query).sort("revision", -1).limit(limit + 1))
    more = len(rows) > limit
    rows = rows[:limit]
    return {
        "items": [service.revision_view(db, r) for r in rows],
        "next_cursor": encode_cursor(str(rows[-1]["revision"])) if more and rows else None,
    }


@router.get(
    "/content-revisions/{revision_id}",
    operation_id="getContentRevision",
    summary="One content revision: immutable payload, manifest, QA and preview path",
)
def get_content_revision(
    revision_id: str,
    _: Principal = Depends(require("getContentRevision")),
    db: Database[dict[str, Any]] = Depends(db_dep),
) -> dict[str, Any]:
    known_id(revision_id, "rev")
    doc = db[service.REVISIONS].find_one({"_id": revision_id})
    if doc is None:
        raise ApiError(404, "not_found", "Not found")
    return service.revision_view(db, doc)


@router.post(
    "/content-revisions/{revision_id}/approvals",
    operation_id="approveContentRevision",
    summary="Final approval of the exact revision, hashes, epoch and state version",
    status_code=201,
)
def approve_content_revision(
    revision_id: str,
    body: Any = Body(...),
    principal: Principal = Depends(require("approveContentRevision")),
    db: Database[dict[str, Any]] = Depends(db_dep),
    contracts: ContractStore = Depends(contracts_dep),
) -> dict[str, Any]:
    known_id(revision_id, "rev")
    request = contract_body(contracts, body, "api.schema.json#/$defs/ApprovalRequest")
    return service.approve(db, contracts, revision_id, request, principal.actor)


@router.post(
    "/content-revisions/{revision_id}/decisions",
    operation_id="decideContentRevision",
    summary="Reject or request changes to the exact revision in final review",
)
def decide_content_revision(
    revision_id: str,
    body: Any = Body(...),
    principal: Principal = Depends(require("decideContentRevision")),
    db: Database[dict[str, Any]] = Depends(db_dep),
    contracts: ContractStore = Depends(contracts_dep),
) -> dict[str, Any]:
    known_id(revision_id, "rev")
    request = contract_body(contracts, body, "api.schema.json#/$defs/ContentDecisionRequest")
    return service.decide(db, contracts, revision_id, request, principal.actor)
