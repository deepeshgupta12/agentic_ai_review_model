"""FastAPI application: request IDs, CORS, contract error envelope, health and v1 routes."""

from __future__ import annotations

import secrets
from typing import Any

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import Response

from app.api import (
    routes_admin,
    routes_auth,
    routes_content,
    routes_corrections,
    routes_findings,
    routes_identity,
    routes_media,
    routes_ops,
    routes_policies,
    routes_projects,
    routes_publication,
    routes_runs,
    routes_sources,
    routes_webhooks,
)
from app.config import get_settings
from app.db import get_db
from app.errors import envelope, install_error_handlers
from app.observability import configure_logging, register_secrets, request_id_var


class RequestIdMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        incoming = request.headers.get("X-Request-ID", "")
        request_id = (
            incoming
            if 8 <= len(incoming) <= 64 and incoming.replace("-", "").isalnum()
            else f"req_{secrets.token_hex(8)}"
        )
        token = request_id_var.set(request_id)
        try:
            response = await call_next(request)
        finally:
            request_id_var.reset(token)
        response.headers["X-Request-ID"] = request_id
        return response


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings.log_level)
    register_secrets(settings.secret_values())
    app = FastAPI(
        title="Agentic Project Intelligence API",
        version="1.0.0",
        docs_url="/docs" if settings.app_mode.value == "fixture" else None,
        redoc_url=None,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[settings.web_origin],
        allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH"],
        allow_headers=["Content-Type", "X-CSRF-Token", "Idempotency-Key", "X-Request-ID"],
    )
    app.add_middleware(RequestIdMiddleware)
    install_error_handlers(app)
    app.include_router(routes_auth.router)
    app.include_router(routes_ops.router)
    app.include_router(routes_projects.router)
    app.include_router(routes_identity.router)
    app.include_router(routes_policies.router)
    app.include_router(routes_runs.router)
    app.include_router(routes_sources.router)
    app.include_router(routes_media.router)
    app.include_router(routes_findings.router)
    app.include_router(routes_admin.router)
    app.include_router(routes_corrections.router)
    app.include_router(routes_content.router)
    app.include_router(routes_publication.router)
    app.include_router(routes_webhooks.router)

    @app.get("/healthz", include_in_schema=False)
    def healthz() -> dict[str, Any]:
        # The console reads the analysis mode and the page's review limits from here, so they are never copied (D69).
        return {
            "status": "ok",
            "mode": settings.app_mode.value,
            "analysis_mode": settings.analysis_mode,
            "page_reviews_max": settings.page_reviews_max,
            "review_words_min": settings.review_words_min,
            "review_words_max": settings.review_words_max,
        }

    @app.get("/readyz", include_in_schema=False, response_model=None)
    def readyz() -> dict[str, Any] | JSONResponse:
        try:
            hello = get_db().client.admin.command("hello")
        except Exception:
            return JSONResponse(
                status_code=503, content=envelope("provider_unavailable", "Database unreachable", retryable=True)
            )
        if not hello.get("isWritablePrimary") or not hello.get("setName"):
            return JSONResponse(
                status_code=503,
                content=envelope(
                    "provider_unavailable", "Database is not a writable replica-set primary", retryable=True
                ),
            )
        return {"status": "ready", "replica_set": hello["setName"]}

    return app


app = create_app()
