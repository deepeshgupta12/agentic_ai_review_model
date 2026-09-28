"""Durable job primitive (Step 03.6, docs/05 'Jobs and checkpoints').

- Unique logical keys make enqueueing idempotent.
- A claim is one atomic update that sets a lease and a new, higher fencing token.
- Every worker write checks status=running and its own fencing token, so a worker
  whose lease expired cannot overwrite its successor.
- Recovery moves expired leases to retry_wait (or failed when attempts are used up)
  and raises the fencing token.
- A human-review pause ends the job (waiting_review) and releases the lease.
Transitions follow contracts/v1/state_machines.json `execution_job`.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from pymongo import ReturnDocument
from pymongo.client_session import ClientSession
from pymongo.database import Database
from pymongo.errors import DuplicateKeyError

from app.db import utcnow
from app.ids import new_id

JOBS = "ai_jobs"
JOB_KINDS = {
    "collect",
    "analyse",
    "resume_after_review",
    "generate_content",
    "deliver_publication",
    "invalidate_dependencies",
    "erase_payloads",
    "scheduled_refresh",
    "evaluate",
}


@dataclass
class Claimed:
    job: dict[str, Any]

    @property
    def id(self) -> str:
        return str(self.job["_id"])

    @property
    def token(self) -> int:
        return int(self.job["lease"]["fencing_token"])


def enqueue(
    db: Database[dict[str, Any]],
    kind: str,
    logical_key: str,
    *,
    run_id: str | None = None,
    project_id: str | None = None,
    max_attempts: int = 5,
    deadline: datetime | None = None,
    session: ClientSession | None = None,
) -> tuple[dict[str, Any], bool]:
    """Create the job unless one with this logical key exists. Returns (job, created)."""
    if kind not in JOB_KINDS:
        raise ValueError(f"unknown job kind {kind!r}")
    now = utcnow()
    doc = {
        "_id": new_id("job"),
        "logical_key": logical_key,
        "kind": kind,
        "run_id": run_id,
        "project_id": project_id,
        "status": "queued",
        "attempts": 0,
        "max_attempts": max_attempts,
        "next_attempt_at": None,
        "lease": None,
        "deadline": deadline,
        "checkpoint_id": None,
        "error": None,
        "fencing": 0,
        "cancel_requested": False,
        "created_at": now,
        "updated_at": now,
    }
    if session is not None:  # inside a transaction a duplicate key would abort it, so look first
        existing = db[JOBS].find_one({"logical_key": logical_key}, session=session)
        if existing is not None:
            return existing, False
    try:
        db[JOBS].insert_one(doc, session=session)
        return doc, True
    except DuplicateKeyError:
        existing = db[JOBS].find_one({"logical_key": logical_key}, session=session)
        assert existing is not None
        return existing, False


def claim(
    db: Database[dict[str, Any]], owner: str, lease_seconds: int, kinds: list[str] | None = None
) -> Claimed | None:
    """Atomically take the oldest claimable job and give it a lease with a fresh fencing token."""
    now = utcnow()
    query: dict[str, Any] = {
        "$or": [
            {"status": "queued"},
            {"status": "retry_wait", "next_attempt_at": {"$lte": now}},
        ],
        "cancel_requested": False,
    }
    if kinds:
        query["kind"] = {"$in": kinds}
    job = db[JOBS].find_one_and_update(
        query,
        [
            {"$set": {"fencing": {"$add": [{"$ifNull": ["$fencing", 0]}, 1]}}},
            {
                "$set": {
                    "status": "running",
                    "attempts": {"$add": ["$attempts", 1]},
                    "lease": {
                        "owner": owner,
                        "expires_at": now + timedelta(seconds=lease_seconds),
                        "fencing_token": "$fencing",
                    },
                    "next_attempt_at": None,
                    "updated_at": now,
                }
            },
        ],
        sort=[("created_at", 1)],
        return_document=ReturnDocument.AFTER,
    )
    return Claimed(job) if job else None


def _owned(job_id: str, token: int) -> dict[str, Any]:
    return {"_id": job_id, "status": "running", "lease.fencing_token": token}


def heartbeat(db: Database[dict[str, Any]], job_id: str, token: int, lease_seconds: int) -> str:
    """Extend the lease. Returns 'ok', 'cancel_requested' or 'lost' (lease taken over or expired)."""
    now = utcnow()
    job = db[JOBS].find_one_and_update(
        _owned(job_id, token),
        {"$set": {"lease.expires_at": now + timedelta(seconds=lease_seconds), "updated_at": now}},
        return_document=ReturnDocument.AFTER,
    )
    if job is None:
        return "lost"
    return "cancel_requested" if job.get("cancel_requested") else "ok"


def complete(db: Database[dict[str, Any]], job_id: str, token: int, checkpoint_id: str | None = None) -> bool:
    update = {
        "$set": {
            "status": "completed",
            "lease": None,
            "error": None,
            "checkpoint_id": checkpoint_id,
            "updated_at": utcnow(),
        }
    }
    return db[JOBS].update_one(_owned(job_id, token), update).modified_count == 1


def pause_for_review(db: Database[dict[str, Any]], job_id: str, token: int, checkpoint_id: str) -> bool:
    """The graph reached a human-review interrupt: save the checkpoint reference and release the lease."""
    update = {
        "$set": {"status": "waiting_review", "lease": None, "checkpoint_id": checkpoint_id, "updated_at": utcnow()}
    }
    return db[JOBS].update_one(_owned(job_id, token), update).modified_count == 1


def backoff_seconds(attempt: int, base: float = 5.0, cap: float = 600.0) -> float:
    """Exponential backoff with full jitter."""
    return random.uniform(0, min(cap, base * (2 ** max(attempt - 1, 0))))  # noqa: S311 - not security sensitive


def fail(
    db: Database[dict[str, Any]], job_id: str, token: int, code: str, message: str, *, retryable: bool
) -> str | None:
    """Record a failure. Retryable failures wait and retry until attempts or the deadline run out."""
    job = db[JOBS].find_one(_owned(job_id, token))
    if job is None:
        return None
    now = utcnow()
    retry = retryable and job["attempts"] < job["max_attempts"] and (job["deadline"] is None or job["deadline"] > now)
    error = {"code": code, "message": message[:500], "retryable": retryable}
    update: dict[str, Any] = {"lease": None, "error": error, "updated_at": now}
    if retry:
        update.update(status="retry_wait", next_attempt_at=now + timedelta(seconds=backoff_seconds(job["attempts"])))
    else:
        update.update(status="failed", next_attempt_at=None)
    result = db[JOBS].update_one(_owned(job_id, token), {"$set": update})
    return update["status"] if result.modified_count == 1 else None


def recover_expired(db: Database[dict[str, Any]]) -> int:
    """Expired leases: back to retry_wait (or failed when out of attempts), fencing raised."""
    now = utcnow()
    expired = {"status": "running", "lease.expires_at": {"$lt": now}}
    result = db[JOBS].update_many(
        expired,
        [
            {
                "$set": {
                    "fencing": {"$add": [{"$ifNull": ["$fencing", 0]}, 1]},
                    "status": {"$cond": [{"$lt": ["$attempts", "$max_attempts"]}, "retry_wait", "failed"]},
                    "next_attempt_at": {"$cond": [{"$lt": ["$attempts", "$max_attempts"]}, now, None]},
                    "lease": None,
                    "error": {
                        "code": "lease_expired",
                        "message": "The worker stopped renewing its lease",
                        "retryable": True,
                    },
                    "updated_at": now,
                }
            }
        ],
    )
    return result.modified_count


def cancel(db: Database[dict[str, Any]], job_id: str) -> str | None:
    """Cancel now if not running; a running job is asked to stop at its next heartbeat."""
    now = utcnow()
    immediate = db[JOBS].find_one_and_update(
        {"_id": job_id, "status": {"$in": ["queued", "retry_wait", "waiting_review"]}},
        {"$set": {"status": "cancelled", "lease": None, "next_attempt_at": None, "updated_at": now}},
        return_document=ReturnDocument.AFTER,
    )
    if immediate:
        return "cancelled"
    requested = db[JOBS].update_one(
        {"_id": job_id, "status": "running"}, {"$set": {"cancel_requested": True, "updated_at": now}}
    )
    return "cancel_requested" if requested.modified_count == 1 else None


def acknowledge_cancel(db: Database[dict[str, Any]], job_id: str, token: int) -> bool:
    """The worker stopped cooperatively after a cancel request; valid results so far are kept."""
    update = {"$set": {"status": "cancelled", "lease": None, "updated_at": utcnow()}}
    return db[JOBS].update_one({**_owned(job_id, token), "cancel_requested": True}, update).modified_count == 1


def job_view(doc: dict[str, Any]) -> dict[str, Any]:
    """Contract Job shape (operations.schema.json): internal fields removed."""
    from app.contracts import to_view

    view = to_view({k: v for k, v in doc.items() if k not in ("fencing", "cancel_requested")})
    assert view is not None
    return view
