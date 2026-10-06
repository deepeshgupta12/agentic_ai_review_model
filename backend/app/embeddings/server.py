"""The embedder service (Step 07, D51): one bge-m3 model behind a small internal HTTP API.

POST /v1/embed {"texts": [...]} returns {"model", "dim", "vectors"}; GET /health says whether the model is loaded.
It listens only on the Compose network (no published port), takes at most MAX_TEXTS texts of MAX_CHARS characters,
keeps no text, and logs only counts. The model is fetched and checked once at start-up.
"""

from __future__ import annotations

import logging
import threading
from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from app.config import get_settings
from app.embeddings.client import model_label
from app.embeddings.model import Bgem3, fetch_model
from app.observability import configure_logging, log_event

logger = logging.getLogger("embedder")
MAX_TEXTS = 64
MAX_CHARS = 8000


class EmbedRequest(BaseModel):
    texts: list[str] = Field(min_length=1, max_length=MAX_TEXTS)


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings.log_level)
    state: dict[str, Any] = {"model": None}
    lock = threading.Lock()  # one batch at a time: memory stays bounded
    app = FastAPI(title="embedder", docs_url=None, redoc_url=None, openapi_url=None)

    @app.on_event("startup")
    def load() -> None:
        files = fetch_model(settings)
        state["model"] = Bgem3(files, max_tokens=settings.embedding_max_tokens, threads=settings.embedding_threads)
        log_event(logger, "embedder ready", model=model_label(settings))

    @app.get("/health")
    def health() -> dict[str, Any]:
        return {"ready": state["model"] is not None, "model": model_label(settings), "dim": settings.embedding_dim}

    @app.post("/v1/embed")
    def embed(body: EmbedRequest) -> dict[str, Any]:
        if state["model"] is None:
            raise HTTPException(503, "model not loaded")
        texts = [t[:MAX_CHARS] for t in body.texts]
        with lock:
            vectors = state["model"].embed(texts)
        return {"model": model_label(settings), "dim": int(vectors.shape[1]), "vectors": vectors.round(6).tolist()}

    return app


app = create_app()
