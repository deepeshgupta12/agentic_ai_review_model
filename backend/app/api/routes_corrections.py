"""Public corrections and their moderation queue (Step 09; docs/09 Corrections and the public page).

A reader of a project page can report a correction without signing in: a short message, an optional contact and the
revision they saw. The `website` field is a honeypot that must stay empty (the contract refuses anything else), and
each client address may send `CORRECTIONS_PER_HOUR` reports; the address is kept only as a salted hash for that count.
The contact is personal data: it is stored on the correction for the moderator and never logged or audited.
Moderators resolve or dismiss a correction with a reason; a substantive correction then goes through the normal
finding or review edit and approval path.
"""

from __future__ import annotations

import hashlib
from datetime import timedelta
from typing import Any

from fastapi import APIRouter, Body, Depends, Query, Request
from pymongo.client_session import ClientSession
from pymongo.database import Database

from app import audit
from app.api.deps import Principal, contract_body, contracts_dep, db_dep, known_id, require, settings_dep
from app.api.routes_ops import decode_cursor, encode_cursor
from app.config import Settings
from app.contracts import ContractStore, to_view
from app.db import run_in_transaction, utcnow
from app.decisions import record_decision
from app.errors import ApiError
from app.ids import new_id

router = APIRouter(prefix="/v1", tags=["corrections"])
COLLECTION = "ai_corrections"
STATUSES = {"received", "in_review", "resolved", "dismissed"}
STATUS_FOR = {"resolve": "resolved", "dismiss": "dismissed"}


def _client_key(request: Request, settings: Settings) -> str:
    host = request.client.host if request.client else "unknown"
    salt = settings.session_secret.get_secret_value() if settings.session_secret else "corrections"
    return hashlib.sha256(f"correction|{salt}|{host}".encode()).hexdigest()  # same shape as login attempt keys


@router.post(
    "/public/projects/{slug}/corrections",
    operation_id="submitCorrection",
    summary="Report a correction from the public project page",
    status_code=202,
)
def submit_correction(
    slug: str,
    request: Request,
    body: Any = Body(...),
    db: Database[dict[str, Any]] = Depends(db_dep),
    contracts: ContractStore = Depends(contracts_dep),
    settings: Settings = Depends(settings_dep),
) -> dict[str, Any]:
    data = contract_body(contracts, body, "api.schema.json#/$defs/CorrectionRequest")
    project = db["projects"].find_one({"slug": slug}, {"_id": 1})
    if project is None:
        raise ApiError(404, "not_found", "Not found")
    key = _client_key(request, settings)
    since = utcnow() - timedelta(hours=1)
    if db["login_attempts"].count_documents({"key": key, "at": {"$gte": since}}) >= settings.corrections_per_hour:
        raise ApiError(429, "rate_limited", "Too many reports from this address; try again later", retryable=True)
    revision_id = data["revision_id"]
    if revision_id is not None and (
        db["ai_content_revisions"].find_one({"_id": revision_id, "project_id": project["_id"]}, {"_id": 1}) is None
    ):
        revision_id = None  # a stale or foreign revision ID is not an error for the reader; it is just not linked
    now = utcnow()
    correction_id = new_id("cor")
    db["ai_corrections"].insert_one(
        {
            "_id": correction_id,
            "project_id": project["_id"],
            "locale": "en-IN",
            "revision_id": revision_id,
            "message": data["message"].strip(),
            "contact": (data["contact"] or "").strip() or None,
            "status": "received",
            "decision_id": None,
            "created_at": now,
        }
    )
    db["login_attempts"].insert_one({"key": key, "at": now, "succeeded": True})
    audit.record(db, "correction.received", "correction", correction_id, audit.PUBLIC_ACTOR)
    return {"correction_id": correction_id, "status": "received"}


@router.get("/corrections", operation_id="listCorrections", summary="Reported corrections, newest first")
def list_corrections(
    _: Principal = Depends(require("listCorrections")),
    db: Database[dict[str, Any]] = Depends(db_dep),
    status: str | None = Query(default=None),
    project_id: str | None = Query(default=None),
    cursor: str | None = Query(default=None),
    limit: int = Query(default=25, ge=1, le=100),
) -> dict[str, Any]:
    query: dict[str, Any] = {}
    if status is not None:
        if status not in STATUSES:
            raise ApiError(
                422, "validation_failed", "Unknown status", fields=[{"path": "status", "message": status[:50]}]
            )
        query["status"] = status
    if project_id is not None:
        query["project_id"] = project_id
    before = decode_cursor(cursor)
    if before:
        query["_id"] = {"$lt": before}
    rows = list(db[COLLECTION].find(query).sort("_id", -1).limit(limit + 1))
    more = len(rows) > limit
    rows = rows[:limit]
    return {
        "items": [to_view(r) for r in rows],
        "next_cursor": encode_cursor(rows[-1]["_id"]) if more and rows else None,
    }


@router.post(
    "/corrections/{correction_id}/decisions",
    operation_id="decideCorrection",
    summary="Resolve or dismiss a reported correction with a reason",
)
def decide_correction(
    correction_id: str,
    body: Any = Body(...),
    principal: Principal = Depends(require("decideCorrection")),
    db: Database[dict[str, Any]] = Depends(db_dep),
    contracts: ContractStore = Depends(contracts_dep),
) -> dict[str, Any]:
    known_id(correction_id, "cor")
    request = contract_body(contracts, body, "api.schema.json#/$defs/CorrectionDecisionRequest")
    to = STATUS_FOR[request["action"]]

    def write(session: ClientSession) -> str:
        correction = db[COLLECTION].find_one({"_id": correction_id}, session=session)
        if correction is None:
            raise ApiError(404, "not_found", "Not found")
        current = correction["status"]
        if not contracts.transition_allowed("correction", current, to, principal.role):
            raise ApiError(409, "invalid_transition", f"A {current} correction cannot be {to}")
        decision_id = record_decision(
            db,
            target_type="correction",
            target_id=correction_id,
            revision=None,
            action=request["action"],
            reason=request["reason"],
            actor=principal.actor,
            session=session,
        )
        changed = db[COLLECTION].update_one(
            {"_id": correction_id, "status": current},
            {"$set": {"status": to, "decision_id": decision_id}},
            session=session,
        )
        if changed.modified_count != 1:
            raise ApiError(409, "version_conflict", "The correction changed; reload it")
        audit.record(
            db,
            "correction.decided",
            "correction",
            correction_id,
            principal.actor,
            details={"action": request["action"], "from": current, "to": to},
            session=session,
        )
        return decision_id

    decision_id = run_in_transaction(db.client, write)
    view = to_view(db["ai_review_decisions"].find_one({"_id": decision_id}))
    assert view is not None
    return view
