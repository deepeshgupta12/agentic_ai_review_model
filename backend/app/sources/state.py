"""Connector cursors and the fetch log (ConnectorState; Step 05.4, 05.7; docs/06 rule 2).

A page's records are stored before its cursor moves, in one transaction where both happen together, so a crash
replays the page and the unique source keys absorb the repeat. The fetch log records each fetch decision
(policy family and version, robots.txt basis, outcome and status), never content.
"""

from __future__ import annotations

import hashlib
from datetime import datetime
from typing import Any

from pymongo.client_session import ClientSession
from pymongo.database import Database
from pymongo.errors import DuplicateKeyError

from app.db import utcnow

STATE = "ai_connector_state"
FETCH_LOG = "ai_fetch_log"


def state_id(connector_id: str, project_id: str | None, query_key: str) -> str:
    return hashlib.sha256(f"{connector_id}|{project_id or '-'}|{query_key}".encode()).hexdigest()


def get(
    db: Database[dict[str, Any]],
    connector_id: str,
    project_id: str | None,
    query_key: str,
    session: ClientSession | None = None,
) -> dict[str, Any]:
    doc = db[STATE].find_one({"_id": state_id(connector_id, project_id, query_key)}, session=session)
    return doc or {
        "_id": state_id(connector_id, project_id, query_key),
        "connector_id": connector_id,
        "project_id": project_id,
        "query_key": query_key,
        "cursor": None,
        "watermark": None,
        "last_success_at": None,
        "last_error": None,
        "coverage": "partial",
        "version": 0,
    }


def save(
    db: Database[dict[str, Any]],
    state: dict[str, Any],
    *,
    cursor: str | None,
    coverage: str,
    watermark: datetime | None = None,
    error: dict[str, Any] | None = None,
    session: ClientSession | None = None,
) -> dict[str, Any]:
    """Advance the cursor (or record an error) at the expected version; a new partition is inserted whole."""
    now = utcnow()
    changes: dict[str, Any] = {"cursor": cursor, "coverage": coverage}
    if error is None:
        changes.update(last_success_at=now, last_error=None)
        if watermark is not None:
            changes["watermark"] = watermark
    else:
        changes["last_error"] = {**error, "at": now}
    updated = {**state, **changes, "version": state["version"] + 1}
    if state["version"] == 0:
        try:
            db[STATE].insert_one(updated, session=session)
        except DuplicateKeyError as exc:
            raise RuntimeError("connector state was created concurrently") from exc
        return updated
    result = db[STATE].update_one(
        {"_id": state["_id"], "version": state["version"]},
        {"$set": changes, "$inc": {"version": 1}},
        session=session,
    )
    if result.modified_count != 1:
        raise RuntimeError("connector state changed concurrently")
    return updated


def log_fetch(db: Database[dict[str, Any]], entry: dict[str, Any], session: ClientSession | None = None) -> None:
    db[FETCH_LOG].insert_one({**entry, "at": utcnow()}, session=session)
