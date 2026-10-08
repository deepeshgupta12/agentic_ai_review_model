"""Client for the embedder service (Step 07, D51). Search and the embedding job call it; when it is down or not
configured, callers fall back to keyword ranking and say so."""

from __future__ import annotations

from typing import Any, Protocol

import httpx

from app.config import Settings


class EmbeddingUnavailable(Exception):
    pass


def model_label(settings: Settings) -> str:
    """What a stored vector was made with; a different label means the vector must be made again."""
    return f"{settings.embedding_model}@{settings.embedding_revision[:12]}:{settings.embedding_file}"


class Embedder(Protocol):
    model: str

    def embed(self, texts: list[str]) -> list[list[float]]: ...


class HttpEmbedder:
    def __init__(self, settings: Settings, timeout: float | None = None) -> None:
        self.url = settings.embedding_url.rstrip("/")
        self.timeout = timeout if timeout is not None else settings.embedding_query_timeout_seconds
        self.model = ""

    def ready(self) -> bool:
        try:
            return bool(httpx.get(f"{self.url}/health", timeout=5).json().get("ready"))
        except (httpx.HTTPError, ValueError):
            return False

    def embed(self, texts: list[str]) -> list[list[float]]:
        try:
            response = httpx.post(f"{self.url}/v1/embed", json={"texts": texts}, timeout=self.timeout)
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise EmbeddingUnavailable(f"embedder: {type(exc).__name__}: {str(exc)[:160]}") from exc
        body: dict[str, Any] = response.json()
        self.model = body["model"]
        return [list(v) for v in body["vectors"]]


def default_embedder(settings: Settings, *, for_job: bool = False) -> HttpEmbedder | None:
    """Search waits at most EMBEDDING_QUERY_TIMEOUT_SECONDS, then uses keywords; the embedding job waits longer."""
    if not (settings.embedding_enabled and settings.embedding_url):
        return None
    return HttpEmbedder(settings, settings.embedding_job_timeout_seconds if for_job else None)
