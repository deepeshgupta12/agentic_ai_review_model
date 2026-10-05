"""Scheduler process. Step 03 runs lease recovery on a timer and Step 05 finishes collection runs;
Step 13 adds refresh schedules (unique project/window job keys, so duplicate ticks never duplicate runs)."""

from __future__ import annotations

import logging
import signal
import threading
from typing import Any

from app.config import get_settings
from app.db import get_db
from app.jobs import queue
from app.observability import configure_logging, log_event, register_secrets

logger = logging.getLogger("scheduler")


def tick() -> int:
    db = get_db()
    recovered = queue.recover_expired(db)
    finish_runs(db)
    expire_sources(db)
    start_clustering(db)
    return recovered


def start_clustering(db: Any) -> bool:
    """Step 07: new evidence gets its origin cluster within the hour (a worker job; D50)."""
    from app.evidence.clusters import start_clustering as start

    return start(db)


def expire_sources(db: Any) -> int:
    """Retention (Step 05.7): sources older than their family's retention expire; erasure follows invalidation."""
    from app.contracts import get_contracts
    from app.sources.lifecycle import expire_due

    return expire_due(db.client, db, get_contracts())


def finish_runs(db: Any) -> int:
    """Safety net for Step 05 runs: a run whose collect jobs have all ended moves on to analysing even when two
    jobs finished at the same moment and each saw the other still running."""
    from app.sources.collection import RUNS, finish_if_done

    finished = 0
    for run in db[RUNS].find({"stage": "collecting"}, {"_id": 1}):
        finished += int(finish_if_done(db.client, db, run["_id"]))
    return finished


def main() -> None:
    settings = get_settings()
    configure_logging(settings.log_level)
    register_secrets(settings.secret_values())
    stopping = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: stopping.set())
    signal.signal(signal.SIGINT, lambda *_: stopping.set())
    log_event(logger, "scheduler started", interval_seconds=settings.job_lease_seconds)
    while not stopping.wait(settings.job_lease_seconds):
        try:
            recovered = tick()
            if recovered:
                log_event(logger, "recovered expired leases", count=recovered)
        except Exception:
            logger.exception("scheduler tick failed")
    log_event(logger, "scheduler stopped")


if __name__ == "__main__":
    main()
