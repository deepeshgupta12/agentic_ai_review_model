"""Scheduler process. Step 03 runs lease recovery on a timer; Step 13 adds refresh schedules
(unique project/window job keys, so duplicate ticks never duplicate runs)."""

from __future__ import annotations

import logging
import signal
import threading

from app.config import get_settings
from app.db import get_db
from app.jobs import queue
from app.observability import configure_logging, log_event, register_secrets

logger = logging.getLogger("scheduler")


def tick() -> int:
    return queue.recover_expired(get_db())


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
