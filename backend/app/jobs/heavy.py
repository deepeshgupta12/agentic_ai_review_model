"""One heavy model at a time (D52; the product owner's Docker limit is 4 GB, I18).

Whisper in the media worker (about 1.6 GB while transcribing) and bge-m3 in the embedder (about 1.1 GB while
embedding a long text) do not fit together beside MongoDB in a 4 GB Docker VM. So they never run at the same time,
and transcription, which a person asked for, goes first:
- a `process_media` job waits (deferred, no attempt used) while an `embed_evidence` job is running; that job stops
  after its current text as soon as transcription is waiting, so the wait is seconds;
- an `embed_evidence` job does not start while transcription is running or waiting, and the scheduler does not queue
  one then.
A short search query still uses the embedder at any time; it is small.
"""

from __future__ import annotations

from typing import Any

from pymongo.database import Database

from app.db import utcnow
from app.jobs.queue import JOBS

MEDIA = "process_media"
EMBED = "embed_evidence"


def running(db: Database[dict[str, Any]], kind: str) -> bool:
    live = {"kind": kind, "status": "running", "lease.expires_at": {"$gt": utcnow()}}
    return bool(db[JOBS].count_documents(live, limit=1))


def waiting(db: Database[dict[str, Any]], kind: str) -> bool:
    return bool(db[JOBS].count_documents({"kind": kind, "status": {"$in": ["queued", "retry_wait"]}}, limit=1))


def transcription_pending(db: Database[dict[str, Any]]) -> bool:
    return running(db, MEDIA) or waiting(db, MEDIA)
