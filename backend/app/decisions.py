"""Append-only review decisions (content.schema.json ReviewDecision). The actor is always a signed-in person."""

from __future__ import annotations

from typing import Any

from pymongo.client_session import ClientSession
from pymongo.database import Database

from app.db import utcnow
from app.ids import new_id
from app.observability import request_id_var


def record_decision(
    db: Database[dict[str, Any]],
    *,
    target_type: str,
    target_id: str,
    revision: int | None,
    action: str,
    reason: str | None,
    actor: dict[str, Any],
    session: ClientSession | None = None,
) -> str:
    if actor.get("kind") != "user":
        raise ValueError("decisions are made by people only")
    decision_id = new_id("dec")
    db["ai_review_decisions"].insert_one(
        {
            "_id": decision_id,
            "target": {"type": target_type, "id": target_id, "revision": revision},
            "action": action,
            "reason": reason,
            "actor": actor,
            "binding": None,
            "idempotency_key": None,
            "request_id": request_id_var.get() or "unknown",
            "created_at": utcnow(),
        },
        session=session,
    )
    return decision_id
