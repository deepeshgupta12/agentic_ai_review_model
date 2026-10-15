"""Publication: activation, delivery verification, rollback, unpublish and the public read (docs/05; D08).

The control document `ai_publication_state` (one per project and locale) is the authority. Activation is one
compare-and-set on it, with the expected state version, the eligibility epoch the approval was bound to and the
approved pointer, wrapped in one transaction with the operation record and its delivery job, so neither can exist
without the other. Before that, the backend re-checks what no model and no console can vouch for: the revision is the
approved one, its payload still hashes to the approved hash, the approval was a person's, no invalidation is pending
and every finding and review it rests on is still approved and eligible.

Delivery is separate and verified: a worker asks the web app to refresh the page (signed revalidation route), then
reads the rendered page and compares its revision marker and hash with what was activated. Only then is the operation
`verified`; until then the console shows `delivery_pending`, and after repeated failures `failed` (the activation
stands). Rollback re-checks the earlier revision like a publication; unpublish serves the empty state. The public read
returns only the active revision while serving is active, never a draft or the newest revision.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import re
from collections.abc import Callable
from typing import Any

import httpx
from pymongo.client_session import ClientSession
from pymongo.database import Database

from app import audit
from app.config import Settings, get_settings
from app.content.hashing import content_hash
from app.content.service import REVISIONS, STATES, dependency_problems, publication_state, state_id
from app.contracts import ContractStore, to_view
from app.db import iso, run_in_transaction, utcnow
from app.errors import ApiError
from app.ids import new_id
from app.jobs import queue

OPERATIONS = "ai_publication_operations"
DELIVER = "deliver_publication"
MAX_DELIVERY_ATTEMPTS = 6
MARKER = re.compile(r"data-insights-(state|revision|hash)=\"([^\"]*)\"")


def operation_view(doc: dict[str, Any]) -> dict[str, Any]:
    view = to_view(doc)
    assert view is not None
    return view


def state_view(db: Database[dict[str, Any]], project_id: str, locale: str = "en-IN") -> dict[str, Any]:
    state = publication_state(db, project_id, locale)
    operations = db[OPERATIONS].find({"project_id": project_id, "locale": locale}).sort("created_at", -1).limit(20)
    view = to_view({k: v for k, v in state.items() if k != "_id"}, id_field=None)
    return {"state": view, "recent_operations": [operation_view(o) for o in operations]}


def _scoped_key(actor: dict[str, Any], kind: str, key: str | None) -> str:
    if key is None or not 8 <= len(key) <= 128:
        raise ApiError(
            422,
            "validation_failed",
            "The Idempotency-Key header is required (8 to 128 characters)",
            fields=[{"path": "Idempotency-Key", "message": "missing or wrong length"}],
        )
    return hashlib.sha256(f"{actor['user_id']}|{kind}|{key}".encode()).hexdigest()


def _replay(db: Database[dict[str, Any]], scoped: str, digest: str) -> dict[str, Any] | None:
    existing = db[OPERATIONS].find_one({"idempotency_key": scoped})
    if existing is None:
        return None
    if existing["request_digest"] != digest:
        raise ApiError(409, "idempotency_conflict", "This Idempotency-Key was used with a different request")
    return operation_view(existing)


def _approved_revision(
    db: Database[dict[str, Any]], state: dict[str, Any], revision_id: str, session: ClientSession | None
) -> tuple[dict[str, Any], dict[str, Any]]:
    """The revision and its approval decision, re-checked (docs/05 steps 2-3); ApiError otherwise."""
    revision = db[REVISIONS].find_one({"_id": revision_id}, session=session)
    if revision is None or revision["project_id"] != state["project_id"] or revision["locale"] != state["locale"]:
        raise ApiError(404, "not_found", "Not found")
    if content_hash(revision["payload"]) != revision["payload_sha256"]:
        raise ApiError(409, "hash_mismatch", "The stored revision no longer matches its hash")
    if revision["lifecycle"] != "approved":
        raise ApiError(
            409, "approval_required", f"Revision {revision['revision']} is {revision['lifecycle']}, not approved"
        )
    decision = db["ai_review_decisions"].find_one(
        {"target.type": "content_revision", "target.id": revision_id, "action": "approve"},
        sort=[("created_at", -1)],
        session=session,
    )
    binding = (decision or {}).get("binding") or {}
    if decision is None or decision["actor"].get("kind") != "user":
        raise ApiError(409, "approval_required", "No approval by a person exists for this revision")
    if (
        binding.get("payload_sha256") != revision["payload_sha256"]
        or binding.get("manifest_sha256") != revision["manifest_sha256"]
    ):
        raise ApiError(409, "approval_required", "The approval was for different content")
    if state["pending_invalidation"]:
        raise ApiError(409, "ineligible_dependency", "An evidence invalidation is pending for this project")
    if binding.get("eligibility_epoch") != state["eligibility_epoch"]:
        raise ApiError(409, "ineligible_dependency", "Evidence eligibility changed after the approval; approve again")
    problems = dependency_problems(db, revision["manifest"], session)
    if problems:
        raise ApiError(409, "ineligible_dependency", "Cannot publish: " + "; ".join(problems)[:500])
    return revision, decision


def _pointer(revision: dict[str, Any]) -> dict[str, Any]:
    return {
        "revision_id": revision["_id"],
        "revision": revision["revision"],
        "payload_sha256": revision["payload_sha256"],
        "manifest_sha256": revision["manifest_sha256"],
    }


def _operation(
    *,
    kind: str,
    state: dict[str, Any],
    target: dict[str, Any] | None,
    expected: int,
    scoped: str,
    digest: str,
    actor: dict[str, Any],
    reason: str | None,
) -> dict[str, Any]:
    now = utcnow()
    return {
        "_id": new_id("pub"),
        "kind": kind,
        "project_id": state["project_id"],
        "locale": state["locale"],
        "target": target,
        "expected_state_version": expected,
        "idempotency_key": scoped,
        "request_digest": digest,
        "actor": actor,
        "reason": reason,
        "status": "delivery_pending",
        "attempts": 0,
        "revalidation": {"requested_at": None, "acknowledged_at": None, "http_status": None},
        "verification": {"verified_at": None, "rendered_revision_id": None, "rendered_payload_sha256": None},
        "error": None,
        "rolled_back_by": None,
        "created_at": now,
        "activated_at": now,
    }


def _activate(
    db: Database[dict[str, Any]],
    contracts: ContractStore,
    state: dict[str, Any],
    operation: dict[str, Any],
    set_fields: dict[str, Any],
    epoch: int,
    match: dict[str, Any],
    session: ClientSession,
) -> None:
    problems = contracts.errors(operation_view(operation), "publication.schema.json#/$defs/PublicationOperation")
    if problems:
        raise ApiError(422, "validation_failed", "Operation does not meet the contract: " + "; ".join(problems[:3]))
    moved = db[STATES].update_one(
        {
            "_id": state["_id"],
            "version": operation["expected_state_version"],
            "eligibility_epoch": epoch,
            "pending_invalidation": False,
            **match,
        },
        {
            "$set": {
                **set_fields,
                "pending_intent": {"operation_id": operation["_id"], "kind": "deliver", "created_at": utcnow()},
                "updated_at": utcnow(),
            },
            "$inc": {"version": 1},
        },
        session=session,
    )
    if moved.modified_count != 1:
        raise ApiError(
            409, "version_conflict", "The publication state changed; reload it", current_version=state["version"]
        )
    db[OPERATIONS].insert_one(operation, session=session)
    queue.enqueue(
        db,
        DELIVER,
        f"{DELIVER}:{operation['_id']}",
        project_id=state["project_id"],
        max_attempts=MAX_DELIVERY_ATTEMPTS,
        session=session,
    )
    audit.record(
        db,
        f"publication.{operation['kind']}",
        "publication_operation",
        operation["_id"],
        operation["actor"],
        revision=(operation["target"] or {}).get("revision"),
        details={"project_id": state["project_id"], "reason": (operation["reason"] or "")[:300] or None},
        session=session,
    )


def _move_run(
    db: Database[dict[str, Any]],
    contracts: ContractStore,
    project_id: str,
    to: str,
    role: str,
    note: str,
    actor: dict[str, Any] | None = None,
) -> None:
    from app.workflows.analysis import move_stage

    run = db["ai_runs"].find_one(
        # the run that holds the page now: never a cancelled or published one (audit, 14 Oct 2026)
        {
            "project_id": project_id,
            "content_revision_id": {"$ne": None},
            "stage": {"$nin": ["published", "insufficient_evidence", "cancelled"]},
        },
        sort=[("created_at", -1)],
    )
    if (
        run is not None
        and run["stage"] != to
        and contracts.transition_allowed("workflow_stage", run["stage"], to, role)
    ):
        move_stage(contracts, db, run["_id"], run["stage"], to, role, note, None, actor)


def publish(
    db: Database[dict[str, Any]], contracts: ContractStore, body: dict[str, Any], key: str | None, actor: dict[str, Any]
) -> dict[str, Any]:
    if actor.get("role") != "publisher":
        raise ApiError(403, "forbidden", "Only a publisher can publish")
    scoped = _scoped_key(actor, "publish", key)
    digest = content_hash(body)
    replay = _replay(db, scoped, digest)
    if replay is not None:
        return replay
    if db["projects"].find_one({"_id": body["project_id"]}, {"_id": 1}) is None:
        raise ApiError(404, "not_found", "No such project")

    def write(session: ClientSession) -> dict[str, Any]:
        state = publication_state(db, body["project_id"], body["locale"], session)
        revision, decision = _approved_revision(db, state, body["revision_id"], session)
        if revision["payload_sha256"] != body["payload_sha256"]:
            raise ApiError(409, "hash_mismatch", "That hash is not this revision's")
        if (state.get("approved") or {}).get("revision_id") != revision["_id"]:
            raise ApiError(409, "approval_required", "This revision is not the project's approved revision")
        if body["expected_state_version"] != state["version"]:
            raise ApiError(
                409, "version_conflict", "The publication state changed; reload it", current_version=state["version"]
            )
        operation = _operation(
            kind="publish",
            state=state,
            target=_pointer(revision),
            expected=state["version"],
            scoped=scoped,
            digest=digest,
            actor=actor,
            reason=None,
        )
        active = {**_pointer(revision), "operation_id": operation["_id"], "activated_at": operation["activated_at"]}
        _activate(
            db,
            contracts,
            state,
            operation,
            {"active": active, "serving_state": "active"},
            decision["binding"]["eligibility_epoch"],
            {"approved.revision_id": revision["_id"]},
            session,
        )
        return operation

    operation = run_in_transaction(db.client, write)
    _move_run(db, contracts, body["project_id"], "publishing", "publisher", "Publication requested", actor)
    return operation_view(operation)


def rollback(
    db: Database[dict[str, Any]],
    contracts: ContractStore,
    operation_id: str,
    body: dict[str, Any],
    key: str | None,
    actor: dict[str, Any],
) -> dict[str, Any]:
    """Activate an earlier revision that is still eligible. It must have been published before and still carry a
    person's approval of its exact hash at the current eligibility epoch; withdrawn content never comes back."""
    scoped = _scoped_key(actor, "rollback", key)
    digest = content_hash({"operation_id": operation_id, **body})
    replay = _replay(db, scoped, digest)
    if replay is not None:
        return replay
    current = db[OPERATIONS].find_one({"_id": operation_id})
    if current is None:
        raise ApiError(404, "not_found", "Not found")

    def write(session: ClientSession) -> dict[str, Any]:
        state = publication_state(db, current["project_id"], current["locale"], session)
        target = db[REVISIONS].find_one({"_id": body["target_revision_id"]}, session=session)
        if target is None or target["project_id"] != state["project_id"]:
            raise ApiError(404, "not_found", "Not found")
        if target["lifecycle"] == "withdrawn":
            raise ApiError(409, "ineligible_dependency", "Withdrawn content can never be served again")
        published_before = db[OPERATIONS].find_one(
            {
                "project_id": state["project_id"],
                "target.revision_id": target["_id"],
                "kind": {"$in": ["publish", "rollback"]},
            },
            session=session,
        )
        if published_before is None:
            raise ApiError(409, "approval_required", "Only a revision that was published before can be restored")
        if (state.get("active") or {}).get("revision_id") == target["_id"]:
            raise ApiError(409, "invalid_transition", "That revision is already active")
        # The earlier revision was superseded when a newer one was approved; its own approval must still hold.
        decision = db["ai_review_decisions"].find_one(
            {"target.type": "content_revision", "target.id": target["_id"], "action": "approve"},
            sort=[("created_at", -1)],
            session=session,
        )
        binding = (decision or {}).get("binding") or {}
        if decision is None or binding.get("payload_sha256") != content_hash(target["payload"]):
            raise ApiError(409, "approval_required", "No approval of this revision's exact content exists")
        if binding.get("eligibility_epoch") != state["eligibility_epoch"] or state["pending_invalidation"]:
            raise ApiError(
                409, "ineligible_dependency", "Evidence changed since that revision was approved; it cannot be restored"
            )
        problems = dependency_problems(db, target["manifest"], session)
        if problems:
            raise ApiError(409, "ineligible_dependency", "Cannot restore: " + "; ".join(problems)[:500])
        if body["expected_state_version"] != state["version"]:
            raise ApiError(
                409, "version_conflict", "The publication state changed; reload it", current_version=state["version"]
            )
        operation = _operation(
            kind="rollback",
            state=state,
            target=_pointer(target),
            expected=state["version"],
            scoped=scoped,
            digest=digest,
            actor=actor,
            reason=body["reason"],
        )
        active = {**_pointer(target), "operation_id": operation["_id"], "activated_at": operation["activated_at"]}
        previous = (state.get("active") or {}).get("operation_id")
        _activate(
            db,
            contracts,
            state,
            operation,
            {"active": active, "serving_state": "active"},
            state["eligibility_epoch"],
            {},
            session,
        )
        if previous:
            db[OPERATIONS].update_one(
                {"_id": previous, "status": "verified"},
                {"$set": {"status": "rolled_back", "rolled_back_by": operation["_id"]}},
                session=session,
            )
        return operation

    return operation_view(run_in_transaction(db.client, write))


def unpublish(
    db: Database[dict[str, Any]],
    contracts: ContractStore,
    project_id: str,
    body: dict[str, Any],
    key: str | None,
    actor: dict[str, Any],
) -> dict[str, Any]:
    scoped = _scoped_key(actor, "unpublish", key)
    digest = content_hash({"project_id": project_id, **body})
    replay = _replay(db, scoped, digest)
    if replay is not None:
        return replay
    if db["projects"].find_one({"_id": project_id}, {"_id": 1}) is None:
        raise ApiError(404, "not_found", "No such project")

    def write(session: ClientSession) -> dict[str, Any]:
        state = publication_state(db, project_id, body["locale"], session)
        if state["serving_state"] == "unpublished":
            raise ApiError(409, "invalid_transition", "Nothing is published")
        if (state.get("active") or {}).get("revision_id") != body["current_revision_id"]:
            raise ApiError(
                409, "version_conflict", "The active revision changed; reload it", current_version=state["version"]
            )
        if body["expected_state_version"] != state["version"]:
            raise ApiError(
                409, "version_conflict", "The publication state changed; reload it", current_version=state["version"]
            )
        operation = _operation(
            kind="unpublish",
            state=state,
            target=None,
            expected=state["version"],
            scoped=scoped,
            digest=digest,
            actor=actor,
            reason=body["reason"],
        )
        _activate(
            db,
            contracts,
            state,
            operation,
            {"active": None, "serving_state": "unpublished"},
            state["eligibility_epoch"],
            {},
            session,
        )
        return operation

    return operation_view(run_in_transaction(db.client, write))


# --- delivery --------------------------------------------------------------------------------------------------------


def _signature(secret: str, body: bytes) -> str:
    return hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def read_markers(html: str) -> dict[str, str]:
    """The module root's delivery markers (docs/09): data-insights-state, -revision and -hash."""
    found: dict[str, str] = {}
    for name, value in MARKER.findall(html):
        found.setdefault(name, value)
    return found


def handle_deliver(
    db: Database[dict[str, Any]],
    job: dict[str, Any],
    check: Callable[[], str],
    client: httpx.Client | None = None,
    settings: Settings | None = None,
) -> str | None:
    """Worker handler for `deliver_publication`: refresh the page, then verify what it renders."""
    settings = settings or get_settings()
    operation_id = job["logical_key"].split(":", 1)[1]
    operation = db[OPERATIONS].find_one({"_id": operation_id})
    if operation is None or operation["status"] in ("verified", "failed", "rolled_back"):
        return None
    state = db[STATES].find_one({"_id": state_id(operation["project_id"], operation["locale"])}) or {}
    current = (state.get("pending_intent") or {}).get("operation_id") == operation_id or (
        (state.get("active") or {}).get("operation_id") == operation_id
    )
    if not current:
        _finish(
            db,
            operation_id,
            "failed",
            {"error": {"code": "version_conflict", "message": "A later publication operation replaced this one"}},
        )
        return None
    project = db["projects"].find_one({"_id": operation["project_id"]}, {"slug": 1}) or {}
    slug = project.get("slug", "")
    expected_state = "empty" if operation["kind"] == "unpublish" else "active"
    target = operation["target"] or {}
    own = client or httpx.Client(timeout=15.0, follow_redirects=False)
    try:
        secret = settings.revalidation_secret.get_secret_value() if settings.revalidation_secret else None
        revalidation = dict(operation["revalidation"])
        if secret:
            payload = json.dumps({"slug": slug, "revision_id": target.get("revision_id")}).encode()
            revalidation["requested_at"] = utcnow()
            try:
                response = own.post(
                    f"{settings.web_internal_url}/api/revalidate",
                    content=payload,
                    headers={"content-type": "application/json", "X-Revalidate-Signature": _signature(secret, payload)},
                )
                revalidation["http_status"] = response.status_code
                revalidation["acknowledged_at"] = utcnow() if response.status_code == 200 else None
            except httpx.HTTPError:
                revalidation["http_status"] = None
        try:
            page = own.get(f"{settings.web_internal_url}/projects/{slug}")
            markers = read_markers(page.text) if page.status_code == 200 else {}
        except httpx.HTTPError:
            markers = {}
    finally:
        if client is None:
            own.close()
    attempts = operation["attempts"] + 1
    verified = markers.get("state") == expected_state and (
        expected_state == "empty"
        or (
            markers.get("revision") == target.get("revision_id") and markers.get("hash") == target.get("payload_sha256")
        )
    )
    if verified:
        _finish(
            db,
            operation_id,
            "verified",
            {
                "attempts": attempts,
                "revalidation": revalidation,
                "verification": {
                    "verified_at": utcnow(),
                    "rendered_revision_id": markers.get("revision") or None,
                    "rendered_payload_sha256": markers.get("hash") or None,
                },
            },
        )
        db[STATES].update_one(
            {"_id": state["_id"], "pending_intent.operation_id": operation_id},
            {"$set": {"pending_intent": None, "updated_at": utcnow()}},
        )
        if operation["kind"] == "publish":
            _move_run(
                db,
                _contracts(),
                operation["project_id"],
                "published",
                "system",
                f"Page shows revision {target.get('revision')}",
            )
        audit.record(db, "publication.verified", "publication_operation", operation_id, audit.SYSTEM_ACTOR)
        return None
    seen = f"page shows state {markers.get('state') or 'none'}, revision {markers.get('revision') or 'none'}"
    if attempts >= MAX_DELIVERY_ATTEMPTS:
        _finish(
            db,
            operation_id,
            "failed",
            {
                "attempts": attempts,
                "revalidation": revalidation,
                "error": {"code": "provider_unavailable", "message": f"Delivery not verified: {seen}"},
            },
        )
        return None
    _finish(
        db,
        operation_id,
        "retry_wait",
        {
            "attempts": attempts,
            "revalidation": revalidation,
            "error": {"code": "provider_unavailable", "message": f"Not yet verified: {seen}"},
        },
    )
    raise queue.JobFailure("delivery_not_verified", seen, retryable=True)


def _contracts() -> ContractStore:
    from app.contracts import get_contracts

    return get_contracts()


def _finish(db: Database[dict[str, Any]], operation_id: str, status: str, fields: dict[str, Any]) -> None:
    """Move the operation along its state machine (`publication_operation`): a failure always passes retry_wait."""
    if status == "failed":
        db[OPERATIONS].update_one(
            {"_id": operation_id, "status": "delivery_pending"}, {"$set": {"status": "retry_wait"}}
        )
    db[OPERATIONS].update_one({"_id": operation_id}, {"$set": {"status": status, **fields}})


# --- public read and invalidation -----------------------------------------------------------------------------------


def public_insights(db: Database[dict[str, Any]], slug: str) -> dict[str, Any] | None:
    """PublicInsights for the page, or None: only the active revision while serving is active, and only if it still
    hashes to the activated hash and is approved (never a draft, never the newest revision by date)."""
    project = db["projects"].find_one({"slug": slug}, {"_id": 1})
    if project is None:
        return None
    state = db[STATES].find_one({"_id": state_id(project["_id"])})
    if (
        not state
        or state.get("serving_state") != "active"
        or not state.get("active")
        or state.get("pending_invalidation")
    ):
        return None
    active = state["active"]
    revision = db[REVISIONS].find_one({"_id": active["revision_id"]})
    if revision is None or revision["lifecycle"] not in ("approved", "superseded"):
        return None
    if (
        revision["payload_sha256"] != active["payload_sha256"]
        or content_hash(revision["payload"]) != active["payload_sha256"]
    ):
        return None
    return {
        "revision_id": revision["_id"],
        "revision": revision["revision"],
        "payload_sha256": revision["payload_sha256"],
        "payload": revision["payload"],
    }


def invalidate_serving(
    db: Database[dict[str, Any]], withdrawn: list[dict[str, Any]], session: ClientSession
) -> list[str]:
    """Evidence invalidation (docs/05 "Invalidation path"): for each project with withdrawn content, bump the
    eligibility epoch (old approvals can no longer publish) and, when the active revision was withdrawn, disable
    serving at once and ask for a page refresh. Returns the affected project IDs."""
    affected = sorted({c["project_id"] for c in withdrawn})
    withdrawn_ids = {c["_id"] for c in withdrawn}
    for project_id in affected:
        state = publication_state(db, project_id, "en-IN", session)
        changes: dict[str, Any] = {"updated_at": utcnow()}
        if (state.get("active") or {}).get("revision_id") in withdrawn_ids and state["serving_state"] == "active":
            changes["serving_state"] = "temporarily_disabled"
        if (state.get("approved") or {}).get("revision_id") in withdrawn_ids:
            changes["approved"] = None
        db[STATES].update_one(
            {"_id": state["_id"]}, {"$set": changes, "$inc": {"eligibility_epoch": 1, "version": 1}}, session=session
        )
    return affected


def project_markers_expected(state: dict[str, Any]) -> dict[str, str | None]:
    """What the public page should show now (for operators and tests)."""
    active = state.get("active") or {}
    serving = state.get("serving_state") == "active" and bool(active)
    return {
        "state": "active" if serving else "empty",
        "revision": active.get("revision_id") if serving else None,
        "hash": active.get("payload_sha256") if serving else None,
        "at": iso(state.get("updated_at")),
    }
