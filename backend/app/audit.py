"""Audit events (operations.schema.json AuditEvent). Never contains raw source payload or secrets."""

from __future__ import annotations

from typing import Any

from pymongo.client_session import ClientSession
from pymongo.database import Database

from app.db import utcnow
from app.ids import new_id
from app.observability import request_id_var

SYSTEM_ACTOR = {"kind": "system", "user_id": None, "role": None}
PUBLIC_ACTOR = {"kind": "public", "user_id": None, "role": None}


def user_actor(user_id: str, role: str) -> dict[str, Any]:
    return {"kind": "user", "user_id": user_id, "role": role}


def record(
    db: Database[dict[str, Any]],
    action: str,
    target_type: str,
    target_id: str,
    actor: dict[str, Any],
    *,
    revision: int | None = None,
    details: dict[str, Any] | None = None,
    session: ClientSession | None = None,
) -> str:
    event_id = new_id("aud")
    db["ai_audit_events"].insert_one(
        {
            "_id": event_id,
            "actor": actor,
            "action": action,
            "target": {"type": target_type, "id": target_id, "revision": revision},
            "at": utcnow(),
            "request_id": request_id_var.get(),
            "details": details or {},
        },
        session=session,
    )
    return event_id
