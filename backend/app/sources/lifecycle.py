"""Source lifecycle (record_lifecycle machine; Step 05.6; docs/02 'Retention and migration'; journey J12).

- A source that is withdrawn, deleted or expired stops being eligible at once (eligibility reads the source's
  lifecycle), its accepted links are sent through dependency invalidation, and an `erase_payloads` job removes
  the stored text only after those invalidations have finished. Audit metadata and hashes stay.
- Availability checks tell a temporary failure (-> unavailable) from a deletion, which needs two consecutive
  'gone' results; an edited source becomes a new revision (app.sources.store).
- Retention: a source older than its policy's `retention_days` expires.
- Withdrawal, confirmed deletion and expiry reach older (superseded) revisions too, so no copy of the text stays (D45).
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from pymongo import MongoClient
from pymongo.client_session import ClientSession
from pymongo.database import Database

from app import audit
from app.contracts import ContractStore
from app.db import run_in_transaction, utcnow
from app.errors import ApiError
from app.evidence import retrieval
from app.identity.links import ACTIVE_STATUSES, enqueue_invalidation
from app.jobs import queue
from app.sources import policies

ERASING = {"deleted", "withdrawn", "expired"}
CHECKS = "ai_availability_checks"


class NotReady(Exception):
    """Erasure must wait for dependency invalidation to finish."""


def _ref(source: dict[str, Any]) -> str:
    return f"{source['id']}@{source['revision']}"


def set_lifecycle(
    db: Database[dict[str, Any]],
    contracts: ContractStore,
    source: dict[str, Any],
    to: str,
    actor: dict[str, Any],
    session: ClientSession | None,
    reason: str,
) -> bool:
    """Move one revision along the lifecycle machine; for erasing states, invalidate dependants and queue erasure."""
    role = actor["role"] if actor["kind"] == "user" else "system"
    if source["lifecycle"] == to:
        return False
    if not contracts.transition_allowed("record_lifecycle", source["lifecycle"], to, role):
        raise ApiError(409, "invalid_transition", f"A source that is {source['lifecycle']} cannot become {to}")
    result = db["ai_sources"].update_one(
        {"_id": source["_id"], "lifecycle": source["lifecycle"]}, {"$set": {"lifecycle": to}}, session=session
    )
    if result.modified_count != 1:
        raise ApiError(409, "version_conflict", "The source changed; reload it")
    audit.record(
        db,
        f"source.{to}",
        "source",
        source["id"],
        actor,
        revision=source["revision"],
        details={"from": source["lifecycle"], "reason": reason[:300]},
        session=session,
    )
    if to in ERASING:
        for link in db["ai_project_source_links"].find(
            {
                "source.id": source["id"],
                "source.revision": source["revision"],
                "status": {"$in": sorted(ACTIVE_STATUSES)},
            },
            session=session,
        ):
            enqueue_invalidation(db, link, session)
        queue.enqueue(db, "erase_payloads", f"erase_payloads:source:{_ref(source)}", max_attempts=10, session=session)
    return True


def withdraw(
    client: MongoClient[dict[str, Any]],
    db: Database[dict[str, Any]],
    contracts: ContractStore,
    source_id: str,
    body: dict[str, Any],
    actor: dict[str, Any],
) -> dict[str, Any]:
    """WithdrawalRequest: one revision or every revision of a source."""

    def write(session: ClientSession) -> dict[str, Any]:
        query: dict[str, Any] = {"id": source_id}
        if body["scope"] == "source_revision":
            query["revision"] = body["revision"]
        revisions = list(db["ai_sources"].find(query, session=session))
        if not revisions:
            raise ApiError(404, "not_found", "No such source revision")
        changed = [
            s
            for s in revisions
            if s["lifecycle"] not in ("withdrawn", "deleted", "expired")  # older revisions too (D45)
            and set_lifecycle(db, contracts, s, "withdrawn", actor, session, body["reason"])
        ]
        if body["scope"] == "source_revision" and not changed and revisions[0]["lifecycle"] != "withdrawn":
            raise ApiError(409, "invalid_transition", f"A {revisions[0]['lifecycle']} revision cannot be withdrawn")
        target = changed[0] if changed else revisions[0]
        job = db["ai_jobs"].find_one({"logical_key": f"erase_payloads:source:{_ref(target)}"}, session=session)
        return {
            "job_id": job["_id"] if job else None,
            "run_id": None,
            "operation_id": None,
            "status_path": f"/v1/sources/{source_id}/revisions/{target['revision']}",
        }

    return run_in_transaction(client, write)


def record_check(
    client: MongoClient[dict[str, Any]],
    db: Database[dict[str, Any]],
    contracts: ContractStore,
    source: dict[str, Any],
    outcome: str,
) -> str:
    """Apply an availability result (present | gone | unknown). Returns the lifecycle after the check."""

    def write(session: ClientSession) -> str:
        current = db["ai_sources"].find_one({"_id": source["_id"]}, session=session) or source
        key = _ref(current)
        system = audit.SYSTEM_ACTOR
        seen = {"at": utcnow(), "last_outcome": outcome}
        if outcome == "present":  # resets the count of consecutive 'gone' results
            db[CHECKS].update_one({"_id": key}, {"$set": {**seen, "gone": 0}}, upsert=True, session=session)
        elif outcome == "unknown":  # a temporary failure leaves the count as it was
            db[CHECKS].update_one(
                {"_id": key}, {"$set": seen, "$setOnInsert": {"gone": 0}}, upsert=True, session=session
            )
        if outcome == "present":
            if current["lifecycle"] == "unavailable":
                set_lifecycle(db, contracts, current, "active", system, session, "fetch restored")
                return "active"
            return current["lifecycle"]
        if outcome == "gone":
            doc = db[CHECKS].find_one_and_update(
                {"_id": key},
                {"$inc": {"gone": 1}, "$set": seen},
                upsert=True,
                return_document=True,
                session=session,
            )
            if (doc or {}).get("gone", 1) >= 2:
                set_lifecycle(db, contracts, current, "deleted", system, session, "gone on two consecutive checks")
                for older in db["ai_sources"].find({"id": current["id"], "lifecycle": "superseded"}, session=session):
                    set_lifecycle(
                        db, contracts, older, "deleted", system, session, "the source's deletion was confirmed"
                    )
                return "deleted"
        if current["lifecycle"] in ("active", "stale"):
            set_lifecycle(
                db,
                contracts,
                current,
                "unavailable",
                system,
                session,
                "gone once; confirming on the next check" if outcome == "gone" else "temporary fetch failure",
            )
            return "unavailable"
        return current["lifecycle"]

    return run_in_transaction(client, write)


def expire_due(
    client: MongoClient[dict[str, Any]],
    db: Database[dict[str, Any]],
    contracts: ContractStore,
    now: datetime | None = None,
) -> int:
    """Sources older than their family's current retention expire."""
    now = now or utcnow()
    expired = 0
    for family in db[policies.COLLECTION].distinct("family"):
        policy = policies.current(db, family, at=now)
        if policy is None or not policy["retention_days"]:
            continue
        cutoff = now - timedelta(days=policy["retention_days"])
        for source in db["ai_sources"].find(
            {
                "policy.family": family,
                "collected_at": {"$lt": cutoff},
                "lifecycle": {"$in": ["active", "stale", "superseded"]},
            }
        ):
            reason = f"retention of {policy['retention_days']} days reached"

            def write(session: ClientSession, source: dict[str, Any] = source, reason: str = reason) -> bool:
                return set_lifecycle(
                    db,
                    contracts,
                    source,
                    "expired",
                    audit.SYSTEM_ACTOR,
                    session,
                    reason,
                )

            expired += int(run_in_transaction(client, write))
    return expired


def handle_erase(db: Database[dict[str, Any]], job: dict[str, Any], check: Any) -> str | None:
    """erase_payloads:source:<id>@<revision>. Waits (retryable) until the invalidations have run."""
    ref = job["logical_key"].split(":", 2)[2]
    source = db["ai_sources"].find_one({"_id": ref})
    if source is None or source["lifecycle"] not in ERASING:
        return None
    links = [
        lk["_id"]
        for lk in db["ai_project_source_links"].find(
            {"source.id": source["id"], "source.revision": source["revision"]}, {"_id": 1}
        )
    ]
    pending = (
        db["ai_jobs"].count_documents(
            {
                "kind": "invalidate_dependencies",
                "status": {"$nin": ["completed", "failed", "cancelled"]},
                "logical_key": {"$in": [k for lk in links for k in _keys_for(db, lk)]},
            }
        )
        if links
        else 0
    )
    if pending:
        raise NotReady(f"{pending} dependency invalidation(s) still running")
    check()
    client = db.client

    def write(session: ClientSession) -> None:
        if source["payload_ref"]:
            db["ai_payloads"].delete_one({"_id": source["payload_ref"]["key"]}, session=session)
        db["ai_sources"].update_one({"_id": ref}, {"$set": {"payload_ref": None}}, session=session)
        # A video's transcript and translations go too (Step 06); segment timing and flags stay as metadata.
        segment_refs = [
            text_ref
            for seg in db["ai_media_segments"].find(
                {"source.id": source["id"], "source.revision": source["revision"]}, session=session
            )
            for text_ref in (seg["original_text_ref"], (seg.get("translation") or {}).get("text_ref"))
            if text_ref
        ]
        if segment_refs:
            db["ai_payloads"].delete_many({"_id": {"$in": segment_refs}}, session=session)
        db["ai_evidence"].update_many(
            {"source.id": source["id"], "source.revision": source["revision"]},
            {"$set": {"excerpt_text": None, "lifecycle": source["lifecycle"]}},
            session=session,
        )
        retrieval.remove_source(db, source["id"], source["revision"], session=session)  # the search copy too
        audit.record(
            db,
            "source.erased",
            "source",
            source["id"],
            audit.SYSTEM_ACTOR,
            revision=source["revision"],
            details={"lifecycle": source["lifecycle"]},
            session=session,
        )

    run_in_transaction(client, write)
    return None


def _keys_for(db: Database[dict[str, Any]], link_id: str) -> list[str]:
    return [
        j["logical_key"]
        for j in db["ai_jobs"].find(
            {"kind": "invalidate_dependencies", "logical_key": {"$regex": f"^invalidate_dependencies:link:{link_id}:"}},
            {"logical_key": 1},
        )
    ]
