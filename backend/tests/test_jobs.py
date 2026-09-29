"""UC-18: the durable job primitive (Step 03.6 acceptance: a claimed job survives worker restart;
an expired worker cannot complete a successor's job)."""

from __future__ import annotations

from datetime import timedelta

from app.db import utcnow
from app.jobs import queue
from app.workers import worker


def status(db, job_id):
    return db["ai_jobs"].find_one({"_id": job_id})["status"]


def expire_lease(db, job_id):
    db["ai_jobs"].update_one({"_id": job_id}, {"$set": {"lease.expires_at": utcnow() - timedelta(seconds=1)}})


def test_enqueue_is_idempotent_by_logical_key(db):
    first, created = queue.enqueue(db, "collect", "collect:prj_x:2026-09-28")
    again, created_again = queue.enqueue(db, "collect", "collect:prj_x:2026-09-28")
    assert created and not created_again and first["_id"] == again["_id"]
    assert db["ai_jobs"].count_documents({}) == 1


def test_unknown_kind_is_rejected(db):
    import pytest

    with pytest.raises(ValueError):
        queue.enqueue(db, "do_anything", "k")


def test_claim_is_exclusive_and_sets_lease_and_fencing(db):
    job, _ = queue.enqueue(db, "collect", "k1")
    claimed = queue.claim(db, "worker-a", 30)
    assert claimed is not None and claimed.id == job["_id"] and claimed.token == 1
    assert claimed.job["attempts"] == 1 and claimed.job["lease"]["owner"] == "worker-a"
    assert queue.claim(db, "worker-b", 30) is None


def test_expired_worker_cannot_complete_its_successors_job(db):
    job, _ = queue.enqueue(db, "collect", "k2")
    first = queue.claim(db, "worker-a", 30)
    expire_lease(db, job["_id"])
    assert queue.recover_expired(db) == 1
    assert status(db, job["_id"]) == "retry_wait"
    second = queue.claim(db, "worker-b", 30)
    assert second is not None and second.token > first.token
    assert queue.complete(db, first.id, first.token) is False
    assert queue.heartbeat(db, first.id, first.token, 30) == "lost"
    assert queue.complete(db, second.id, second.token) is True
    assert status(db, job["_id"]) == "completed"


def test_claimed_job_survives_a_worker_restart(db, monkeypatch):
    job, _ = queue.enqueue(db, "collect", "k3")
    queue.claim(db, "crashed-worker", 30)
    expire_lease(db, job["_id"])
    monkeypatch.setitem(worker.HANDLERS, "collect", lambda _db, _job, _check: "ckpt-after-restart")
    assert worker.run_one(db, "new-worker", 30) == "completed"
    doc = db["ai_jobs"].find_one({"_id": job["_id"]})
    assert doc["status"] == "completed" and doc["attempts"] == 2 and doc["checkpoint_id"] == "ckpt-after-restart"


def test_retryable_failure_waits_then_fails_when_attempts_run_out(db):
    job, _ = queue.enqueue(db, "collect", "k4", max_attempts=2)
    c1 = queue.claim(db, "w", 30)
    assert queue.fail(db, c1.id, c1.token, "Timeout", "provider timed out", retryable=True) == "retry_wait"
    db["ai_jobs"].update_one({"_id": job["_id"]}, {"$set": {"next_attempt_at": utcnow() - timedelta(seconds=1)}})
    c2 = queue.claim(db, "w", 30)
    assert c2 is not None and c2.job["attempts"] == 2
    assert queue.fail(db, c2.id, c2.token, "Timeout", "provider timed out", retryable=True) == "failed"
    assert db["ai_jobs"].find_one({"_id": job["_id"]})["error"]["code"] == "Timeout"


def test_retry_is_not_claimed_before_its_time(db):
    queue.enqueue(db, "collect", "k5")
    c = queue.claim(db, "w", 30)
    queue.fail(db, c.id, c.token, "X", "x", retryable=True)
    db["ai_jobs"].update_one({"_id": c.id}, {"$set": {"next_attempt_at": utcnow() + timedelta(minutes=5)}})
    assert queue.claim(db, "w", 30) is None


def test_non_retryable_failure_fails_immediately(db):
    queue.enqueue(db, "collect", "k6")
    c = queue.claim(db, "w", 30)
    assert queue.fail(db, c.id, c.token, "BadInput", "bad", retryable=False) == "failed"


def test_cancel_before_start_and_cooperative_cancel_while_running(db):
    queued, _ = queue.enqueue(db, "collect", "k7")
    assert queue.cancel(db, queued["_id"]) == "cancelled"
    running, _ = queue.enqueue(db, "analyse", "k8")
    c = queue.claim(db, "w", 30)
    assert queue.cancel(db, running["_id"]) == "cancel_requested"
    assert queue.heartbeat(db, c.id, c.token, 30) == "cancel_requested"
    assert queue.acknowledge_cancel(db, c.id, c.token) is True
    assert status(db, running["_id"]) == "cancelled"


def test_pause_for_review_releases_the_lease(db):
    job, _ = queue.enqueue(db, "analyse", "k9")
    c = queue.claim(db, "w", 30)
    assert queue.pause_for_review(db, c.id, c.token, "ckpt-7") is True
    doc = db["ai_jobs"].find_one({"_id": job["_id"]})
    assert doc["status"] == "waiting_review" and doc["lease"] is None and doc["checkpoint_id"] == "ckpt-7"


def test_worker_records_a_missing_handler_as_failed(db):
    queue.enqueue(db, "evaluate", "k10")
    assert worker.run_one(db, "w", 30) == "failed"
    assert db["ai_jobs"].find_one({"logical_key": "k10"})["error"]["code"] == "no_handler"


def test_worker_retries_a_crashing_handler(db, monkeypatch):
    queue.enqueue(db, "analyse", "k11")

    def boom(_db, _job, _check):
        raise RuntimeError("temporary failure")

    monkeypatch.setitem(worker.HANDLERS, "analyse", boom)
    assert worker.run_one(db, "w", 30) == "retry_wait"


def test_every_status_change_is_allowed_by_the_state_machine(db, contracts):
    observed = [
        ("queued", "running"),
        ("running", "retry_wait"),
        ("retry_wait", "running"),
        ("running", "completed"),
        ("running", "failed"),
        ("running", "waiting_review"),
        ("queued", "cancelled"),
        ("running", "cancelled"),
    ]
    for from_state, to_state in observed:
        assert contracts.transition_allowed(
            "execution_job", from_state, to_state, "system"
        ) or contracts.transition_allowed("execution_job", from_state, to_state, "researcher"), (from_state, to_state)


def test_job_view_matches_the_contract(db, contracts):
    job, _ = queue.enqueue(db, "collect", "k12", project_id="prj_01JB0000000000000000000001")
    queue.claim(db, "w", 30)
    doc = db["ai_jobs"].find_one({"_id": job["_id"]})
    assert contracts.errors(queue.job_view(doc), "operations.schema.json#/$defs/Job") == []


def test_list_jobs_endpoint_paginates(api, make_user, db, contracts):
    from .conftest import login

    for n in range(3):
        queue.enqueue(db, "collect", f"page-{n}")
    user = make_user(["admin"])
    login(api, user["email"])
    first = api.get("/v1/ops/jobs", params={"limit": 2}).json()
    assert contracts.errors(first, "api.schema.json#/$defs/JobPage") == []
    assert len(first["items"]) == 2 and first["next_cursor"]
    second = api.get("/v1/ops/jobs", params={"limit": 2, "cursor": first["next_cursor"]}).json()
    assert len(second["items"]) == 1 and second["next_cursor"] is None
    assert {j["id"] for j in first["items"]}.isdisjoint({j["id"] for j in second["items"]})
