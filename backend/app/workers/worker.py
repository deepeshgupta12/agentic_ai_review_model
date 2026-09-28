"""Worker process: recovers expired leases, claims jobs, heartbeats and runs handlers.

Step 04 registers invalidate_dependencies; later steps add collection, analysis and delivery.
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
from app.identity import invalidation
from app.jobs import queue
from app.observability import configure_logging, log_event, register_secrets

logger = logging.getLogger("worker")
Handler = Callable[[Database[dict[str, Any]], dict[str, Any], Callable[[], str]], str | None]
HANDLERS: dict[str, Handler] = {}


class JobCancelled(Exception):
    pass


def register(kind: str) -> Callable[[Handler], Handler]:
    def wrap(func: Handler) -> Handler:
        HANDLERS[kind] = func
        return func

    return wrap


register("invalidate_dependencies")(invalidation.handle)


def run_one(db: Database[dict[str, Any]], owner: str, lease_seconds: int) -> str | None:
    """Claim and run one job. Returns the job's final status, or None when nothing was claimable."""
    queue.recover_expired(db)
    claimed = queue.claim(db, owner, lease_seconds)
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
        while not stop.wait(lease_seconds / 3):
            state["beat"] = queue.heartbeat(db, claimed.id, claimed.token, lease_seconds)
            if state["beat"] != "ok":
                return

    def check() -> str:
        if state["beat"] == "cancel_requested":
            raise JobCancelled
        return state["beat"]

    beater = threading.Thread(target=beat_loop, daemon=True)
    beater.start()
    try:
        checkpoint_id = handler(db, job, check)
        return "completed" if queue.complete(db, claimed.id, claimed.token, checkpoint_id) else "lost"
    except JobCancelled:
        queue.acknowledge_cancel(db, claimed.id, claimed.token)
        return "cancelled"
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
    log_event(logger, "worker started", owner=owner, handlers=sorted(HANDLERS))
    db = get_db()
    while not stopping.is_set():
        try:
            if run_one(db, owner, settings.job_lease_seconds) is None:
                stopping.wait(settings.job_poll_seconds)
        except Exception:
            logger.exception("worker loop error")
            time.sleep(settings.job_poll_seconds)
    log_event(logger, "worker stopped", owner=owner)


if __name__ == "__main__":
    main()
