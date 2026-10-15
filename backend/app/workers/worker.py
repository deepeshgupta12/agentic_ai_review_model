"""Worker process: recovers expired leases, claims jobs, heartbeats and runs handlers.

Registered: invalidate_dependencies (Step 04); collect, erase_payloads, check_availability (Step 05); process_media
(Step 06); cluster_origins, embed_evidence (Step 07); analyse, resume_after_review (Step 08); deliver_publication
(Step 10). WORKER_ROLE splits
them: "media" takes only process_media (the media worker image), "general" takes everything else, "all" (the
default, and tests) takes every kind.
A job without a handler fails visibly instead of silently disappearing.
"""

from __future__ import annotations

import logging
import signal
import socket
import threading
import time
from collections.abc import Callable
from typing import Any

from pymongo.database import Database

from app.config import get_settings
from app.db import get_db
from app.embeddings import jobs as embedding_jobs
from app.evidence import clusters
from app.identity import invalidation
from app.jobs import queue
from app.media import pipeline as media
from app.observability import configure_logging, log_event, register_secrets
from app.publication import service as publication
from app.sources import collection, lifecycle, recheck
from app.workflows import analysis

logger = logging.getLogger("worker")
Handler = Callable[[Database[dict[str, Any]], dict[str, Any], Callable[[], str]], str | None]
HANDLERS: dict[str, Handler] = {}


JobCancelled = queue.JobCancelled
JobLost = queue.JobLost


def register(kind: str) -> Callable[[Handler], Handler]:
    def wrap(func: Handler) -> Handler:
        HANDLERS[kind] = func
        return func

    return wrap


register("invalidate_dependencies")(invalidation.handle)
register("collect")(collection.handle_collect)
register("erase_payloads")(lifecycle.handle_erase)
register("check_availability")(recheck.handle_recheck)
register("process_media")(media.handle_process_media)
register("cluster_origins")(clusters.handle_cluster_origins)
register("embed_evidence")(embedding_jobs.handle_embed_evidence)
register("analyse")(analysis.handle_analyse)
register("resume_after_review")(analysis.handle_resume)
register("deliver_publication")(publication.handle_deliver)
MEDIA_KINDS = ("process_media",)
# The browser journeys' worker (Step 09.7): review continuation, publication delivery and invalidation only. It runs
# with the real environment, so it never takes collection, analysis or media work; continuation calls a model only
# when findings are selected, and the journeys select approved reviews only.
JOURNEY_KINDS = ("resume_after_review", "deliver_publication", "invalidate_dependencies", "erase_payloads")


def kinds_for(role: str) -> list[str] | None:
    if role == "media":
        return list(MEDIA_KINDS)
    if role == "journeys":
        return list(JOURNEY_KINDS)
    if role == "general":
        return [kind for kind in queue.JOB_KINDS if kind not in MEDIA_KINDS]
    return None


def run_one(db: Database[dict[str, Any]], owner: str, lease_seconds: int, kinds: list[str] | None = None) -> str | None:
    """Claim and run one job. Returns the job's final status, or None when nothing was claimable."""
    queue.recover_expired(db)
    claimed = queue.claim(db, owner, lease_seconds, kinds)
    if claimed is None:
        return None
    job = claimed.job
    handler = HANDLERS.get(job["kind"])
    if handler is None:
        queue.fail(
            db, claimed.id, claimed.token, "no_handler", f"No handler for job kind {job['kind']}", retryable=False
        )
        return "failed"

    state = {"beat": "ok"}
    stop = threading.Event()

    def beat_loop() -> None:
        # A database stall does not stop the beating (it is tried again at the next beat); the lease counts as lost
        # only once it has really passed, or the queue says another worker owns the job. A cancel request keeps the
        # beat going, so the lease does not expire before the handler reaches its next check (audit, 14 Oct 2026).
        lease_until = time.monotonic() + lease_seconds
        while not stop.wait(lease_seconds / 3):
            try:
                beat = queue.heartbeat(db, claimed.id, claimed.token, lease_seconds)
            except Exception:
                logger.warning("heartbeat failed; trying again", extra={"job_id": claimed.id})
                if time.monotonic() > lease_until:
                    state["beat"] = "lost"
                    return
                continue
            lease_until = time.monotonic() + lease_seconds
            state["beat"] = beat
            if beat == "lost":
                return

    def check() -> str:
        """Between units of work: stop at once when the run was cancelled or another worker owns the job now."""
        if state["beat"] == "cancel_requested":
            raise JobCancelled
        if state["beat"] == "lost":
            raise JobLost
        return state["beat"]

    beater = threading.Thread(target=beat_loop, daemon=True)
    beater.start()
    try:
        checkpoint_id = handler(db, job, check)
        return "completed" if queue.complete(db, claimed.id, claimed.token, checkpoint_id) else "lost"
    except JobCancelled:
        queue.acknowledge_cancel(db, claimed.id, claimed.token)
        return "cancelled"
    except JobLost:
        log_event(logger, "job lease lost; stopped", level=logging.WARNING, job_id=claimed.id, kind=job["kind"])
        return "lost"
    except queue.Deferred as exc:
        log_event(logger, "job deferred", job_id=claimed.id, kind=job["kind"], reason=exc.reason)
        return queue.defer(db, claimed.id, claimed.token, exc.reason, exc.seconds)
    except queue.PausedForReview as exc:
        log_event(logger, "job waiting for review", job_id=claimed.id, kind=job["kind"])
        paused = queue.pause_for_review(db, claimed.id, claimed.token, exc.checkpoint_id)
        return "waiting_review" if paused else "lost"
    except queue.JobFailure as exc:
        log_event(logger, "job stopped", level=logging.WARNING, job_id=claimed.id, kind=job["kind"], error=exc.code)
        return queue.fail(db, claimed.id, claimed.token, exc.code, exc.message, retryable=exc.retryable)
    except Exception as exc:
        log_event(
            logger, "job failed", level=logging.ERROR, job_id=claimed.id, kind=job["kind"], error=type(exc).__name__
        )
        return queue.fail(db, claimed.id, claimed.token, type(exc).__name__, str(exc), retryable=True)
    finally:
        stop.set()
        beater.join(timeout=1)


def main() -> None:
    settings = get_settings()
    configure_logging(settings.log_level)
    register_secrets(settings.secret_values())
    owner = f"{socket.gethostname()}:{threading.get_native_id()}"
    stopping = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: stopping.set())
    signal.signal(signal.SIGINT, lambda *_: stopping.set())
    kinds = kinds_for(settings.worker_role)
    log_event(logger, "worker started", owner=owner, role=settings.worker_role, kinds=sorted(kinds or HANDLERS))
    db = get_db()
    while not stopping.is_set():
        try:
            if run_one(db, owner, settings.job_lease_seconds, kinds) is None:
                stopping.wait(settings.job_poll_seconds)
        except Exception:
            logger.exception("worker loop error")
            time.sleep(settings.job_poll_seconds)
    log_event(logger, "worker stopped", owner=owner)


if __name__ == "__main__":
    main()
