"""Idempotency-Key handling for mutations that can repeat (docs/03 common behavior).

The key is scoped to the operation and the signed-in user. The same key with the same body returns the
stored response; the same key with a different body returns 409 idempotency_conflict. Records expire
after seven days.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from typing import Any

from pymongo.database import Database
from pymongo.errors import DuplicateKeyError

from app.db import utcnow
from app.errors import ApiError

HEADER = "Idempotency-Key"


def _digest(body: Any) -> str:
    return hashlib.sha256(
        json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    ).hexdigest()


def run_idempotent(
    db: Database[dict[str, Any]],
    *,
    operation_id: str,
    user_id: str,
    key: str | None,
    body: Any,
    compute: Callable[[], dict[str, Any]],
) -> dict[str, Any]:
    if key is None or not 8 <= len(key) <= 128:
        raise ApiError(
            422,
            "validation_failed",
            f"The {HEADER} header is required (8 to 128 characters)",
            fields=[{"path": HEADER, "message": "missing or wrong length"}],
        )
    record_id = hashlib.sha256(f"{operation_id}|{user_id}|{key}".encode()).hexdigest()
    digest = _digest(body)

    def replay(existing: dict[str, Any]) -> dict[str, Any]:
        if existing["digest"] != digest:
            raise ApiError(409, "idempotency_conflict", f"This {HEADER} was used with a different request")
        return dict(existing["response"])

    existing = db["ai_idempotency_keys"].find_one({"_id": record_id})
    if existing is not None:
        return replay(existing)
    response = compute()
    try:
        db["ai_idempotency_keys"].insert_one(
            {
                "_id": record_id,
                "operation_id": operation_id,
                "user_id": user_id,
                "digest": digest,
                "status_code": 200,
                "response": response,
                "created_at": utcnow(),
            }
        )
    except DuplicateKeyError:
        existing = db["ai_idempotency_keys"].find_one({"_id": record_id})
        if existing is not None:
            return replay(existing)
    return response
