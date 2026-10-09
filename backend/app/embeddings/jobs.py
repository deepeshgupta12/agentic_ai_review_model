"""Embedding evidence (Step 07, D51): the `embed_evidence` job fills the vector of every search-index entry that has
none, or one made by another model, one text per request through the embedder service. The scheduler queues it at
most every ten minutes, only when entries are waiting and the embedder says it is ready."""

from __future__ import annotations

import logging
from typing import Any

from pymongo.database import Database

from app.config import Settings, get_settings
from app.db import utcnow
from app.embeddings.client import Embedder, EmbeddingUnavailable, default_embedder, model_label
from app.evidence.retrieval import INDEX, sync_index
from app.jobs import heavy, queue
from app.jobs.queue import Deferred
from app.observability import log_event

logger = logging.getLogger(__name__)
KIND = "embed_evidence"


def pending_query(settings: Settings) -> dict[str, Any]:
    return {"$or": [{"embedding": None}, {"embedding_model": {"$ne": model_label(settings)}}]}


def start_embedding(db: Database[dict[str, Any]], settings: Settings | None = None, *, probe: bool = True) -> bool:
    settings = settings or get_settings()
    embedder = default_embedder(settings, for_job=True) if probe else None
    if not settings.embedding_enabled:
        return False
    sync_index(db)
    if not db[INDEX].count_documents(pending_query(settings), limit=1):
        return False
    if heavy.transcription_pending(db):
        return False  # transcription first: both models do not fit in the 4 GB VM together (D52)
    if embedder is not None and not embedder.ready():
        return False  # nothing is queued while the embedder is down or still loading; search uses keywords
    now = utcnow()
    _, created = queue.enqueue(db, KIND, f"{KIND}:{now:%Y%m%d%H}{now.minute // 10}", max_attempts=5)
    return created


def embed_pending(
    db: Database[dict[str, Any]],
    embedder: Embedder,
    settings: Settings,
    *,
    check: Any = lambda: None,
    limit: int | None = None,
    should_yield: Any = lambda: False,
) -> dict[str, int]:
    """Embed waiting entries in batches; returns counts. Raises EmbeddingUnavailable if the service is down. Stops
    early, between batches, when `should_yield()` says another heavy job needs the memory."""
    done = 0
    label = model_label(settings)
    while limit is None or done < limit:
        if should_yield():
            break
        batch = list(db[INDEX].find(pending_query(settings), {"text": 1}).limit(settings.embedding_batch))
        if not batch:
            break
        check()
        vectors = embedder.embed([doc["text"] for doc in batch])
        if any(len(v) != settings.embedding_dim for v in vectors):
            raise ValueError(f"the embedder returned vectors that are not {settings.embedding_dim}-dimensional")
        for doc, vector in zip(batch, vectors, strict=True):
            db[INDEX].update_one({"_id": doc["_id"]}, {"$set": {"embedding": vector, "embedding_model": label}})
        done += len(batch)
    return {"embedded": done, "waiting": db[INDEX].count_documents(pending_query(settings))}


def handle_embed_evidence(db: Database[dict[str, Any]], job: dict[str, Any], check: Any) -> str | None:
    settings = get_settings()
    embedder = default_embedder(settings, for_job=True)
    if embedder is None:
        return None
    if heavy.transcription_pending(db):
        raise Deferred("transcription is running or waiting; it goes first in the 4 GB VM (D52)", 300)
    sync_index(db)
    try:
        report = embed_pending(
            db, embedder, settings, check=check, should_yield=lambda: heavy.transcription_pending(db)
        )
    except EmbeddingUnavailable:
        raise  # retried with backoff; the embedder may still be loading its model
    log_event(logger, "evidence embedded", **report)
    return None
