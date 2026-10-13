"""Administration and audit (Step 09.6; docs/09 Administration and Operations).

Users and roles are managed by admins only. A new user gets an argon2id password hash; the password itself is never
stored, logged or returned. An admin cannot lock themselves out (deactivate their own account or drop their own admin
role), and deactivating a user ends their sessions at once. Audit events and evaluation results are read-only lists.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Body, Depends, Query
from pymongo.database import Database
from pymongo.errors import DuplicateKeyError

from app import audit
from app.api.deps import Principal, contract_body, contracts_dep, db_dep, known_id, require
from app.api.routes_ops import decode_cursor, encode_cursor
from app.auth.passwords import WeakPasswordError, hash_password
from app.contracts import ContractStore, to_view
from app.db import utcnow
from app.errors import ApiError
from app.ids import new_id

router = APIRouter(prefix="/v1", tags=["admin"])


def user_view(doc: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": doc["_id"],
        "email": doc["email"],
        "display_name": doc["display_name"],
        "roles": doc["roles"],
        "active": doc["active"],
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


@router.get("/admin/users", operation_id="listUsers", summary="Console users and their roles")
def list_users(
    _: Principal = Depends(require("listUsers")),
    db: Database[dict[str, Any]] = Depends(db_dep),
    cursor: str | None = Query(default=None),
    limit: int = Query(default=25, ge=1, le=100),
) -> dict[str, Any]:
    rows, next_cursor = _page(db, "users", {}, cursor, limit)
    return {"items": [user_view(r) for r in rows], "next_cursor": next_cursor}


@router.post("/admin/users", operation_id="createUser", summary="Create a console user", status_code=201)
def create_user(
    body: Any = Body(...),
    principal: Principal = Depends(require("createUser")),
    db: Database[dict[str, Any]] = Depends(db_dep),
    contracts: ContractStore = Depends(contracts_dep),
) -> dict[str, Any]:
    request = contract_body(contracts, body, "api.schema.json#/$defs/UserCreateRequest")
    try:
        password_hash = hash_password(request["password"])
    except WeakPasswordError as exc:
        raise ApiError(422, "validation_failed", str(exc), fields=[{"path": "password", "message": str(exc)}]) from exc
    now = utcnow()
    doc = {
        "_id": new_id("usr"),
        "email": request["email"].strip().lower(),
        "display_name": request["display_name"].strip(),
        "roles": request["roles"],
        "active": True,
        "password_hash": password_hash,
        "created_at": now,
        "updated_at": now,
    }
    try:
        db["users"].insert_one(doc)
    except DuplicateKeyError as exc:
        raise ApiError(409, "version_conflict", "A user with this e-mail address already exists") from exc
    audit.record(
        db, "user.created", "user", doc["_id"], principal.actor, details={"roles": ",".join(sorted(doc["roles"]))}
    )
    return user_view(doc)


@router.patch("/admin/users/{user_id}", operation_id="updateUser", summary="Change a user's name, roles or access")
def update_user(
    user_id: str,
    body: Any = Body(...),
    principal: Principal = Depends(require("updateUser")),
    db: Database[dict[str, Any]] = Depends(db_dep),
    contracts: ContractStore = Depends(contracts_dep),
) -> dict[str, Any]:
    known_id(user_id, "usr")
    request = contract_body(contracts, body, "api.schema.json#/$defs/UserUpdateRequest")
    user = db["users"].find_one({"_id": user_id})
    if user is None:
        raise ApiError(404, "not_found", "Not found")
    if user_id == principal.user_id:
        if request.get("active") is False:
            raise ApiError(422, "validation_failed", "You cannot deactivate your own account")
        if "roles" in request and "admin" not in request["roles"]:
            raise ApiError(422, "validation_failed", "You cannot remove your own admin role")
    changes: dict[str, Any] = {}
    if "display_name" in request and request["display_name"].strip() != user["display_name"]:
        changes["display_name"] = request["display_name"].strip()
    if "roles" in request and sorted(request["roles"]) != sorted(user["roles"]):
        changes["roles"] = request["roles"]
    if "active" in request and request["active"] != user["active"]:
        changes["active"] = request["active"]
    if changes:
        db["users"].update_one({"_id": user_id}, {"$set": {**changes, "updated_at": utcnow()}})
        if changes.get("active") is False:
            db["sessions"].delete_many({"user_id": user_id})
        audit.record(
            db,
            "user.updated",
            "user",
            user_id,
            principal.actor,
            details={
                "fields": ",".join(sorted(changes)),
                "roles": ",".join(sorted(changes["roles"])) if "roles" in changes else None,
                "active": changes.get("active"),
            },
        )
    updated = db["users"].find_one({"_id": user_id})
    assert updated is not None
    return user_view(updated)


def _timestamp(value: str | None, name: str) -> datetime | None:
    if value is None:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ApiError(
            422, "validation_failed", "Invalid time", fields=[{"path": name, "message": "not RFC 3339"}]
        ) from exc


@router.get("/admin/audit-events", operation_id="listAuditEvents", summary="Audit events, newest first")
def list_audit_events(
    _: Principal = Depends(require("listAuditEvents")),
    db: Database[dict[str, Any]] = Depends(db_dep),
    target_type: str | None = Query(default=None),
    target_id: str | None = Query(default=None),
    from_: str | None = Query(default=None, alias="from"),
    to: str | None = Query(default=None),
    cursor: str | None = Query(default=None),
    limit: int = Query(default=25, ge=1, le=100),
) -> dict[str, Any]:
    query: dict[str, Any] = {}
    if target_type:
        query["target.type"] = target_type
    if target_id:
        query["target.id"] = target_id
    window = {k: v for k, v in (("$gte", _timestamp(from_, "from")), ("$lte", _timestamp(to, "to"))) if v}
    if window:
        query["at"] = window
    rows, next_cursor = _page(db, "ai_audit_events", query, cursor, limit)
    return {"items": [to_view(r) for r in rows], "next_cursor": next_cursor}


@router.get("/evaluations", operation_id="listEvaluations", summary="Evaluation runs with metrics and sample sizes")
def list_evaluations(
    _: Principal = Depends(require("listEvaluations")),
    db: Database[dict[str, Any]] = Depends(db_dep),
    cursor: str | None = Query(default=None),
    limit: int = Query(default=25, ge=1, le=100),
) -> dict[str, Any]:
    rows, next_cursor = _page(db, "ai_evaluations", {}, cursor, limit)
    return {"items": [to_view(r) for r in rows], "next_cursor": next_cursor}
