"""Errors in the contract envelope (common.schema.json ErrorEnvelope, docs/03).

Messages are safe to show; internals never leak. 404 is also used when the caller
may not know a record exists.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.observability import request_id_var

logger = logging.getLogger(__name__)

STATUS_CODES = {
    400: "validation_failed",
    401: "unauthenticated",
    403: "forbidden",
    404: "not_found",
    405: "validation_failed",
    409: "version_conflict",
    422: "validation_failed",
    429: "rate_limited",
    503: "provider_unavailable",
}


class ApiError(Exception):
    def __init__(
        self,
        status: int,
        code: str,
        message: str,
        *,
        retryable: bool = False,
        fields: list[dict[str, str]] | None = None,
        current_version: int | None = None,
    ) -> None:
        super().__init__(message)
        self.status, self.code, self.message = status, code, message
        self.retryable, self.fields, self.current_version = retryable, fields or [], current_version


def envelope(
    code: str,
    message: str,
    *,
    retryable: bool = False,
    fields: list[dict[str, str]] | None = None,
    current_version: int | None = None,
) -> dict[str, Any]:
    body: dict[str, Any] = {
        "code": code,
        "message": message,
        "request_id": request_id_var.get() or "unknown",
        "retryable": retryable,
        "fields": fields or [],
    }
    if current_version is not None:
        body["current_version"] = current_version
    return {"error": body}


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def _api_error(_: Request, exc: ApiError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status,
            content=envelope(
                exc.code, exc.message, retryable=exc.retryable, fields=exc.fields, current_version=exc.current_version
            ),
        )

    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, exc: RequestValidationError) -> JSONResponse:
        fields = [
            {
                "path": "/".join(str(p) for p in err.get("loc", []) if p != "body"),
                "message": str(err.get("msg", "invalid")),
            }
            for err in exc.errors()
        ]
        return JSONResponse(
            status_code=422, content=envelope("validation_failed", "Request failed validation", fields=fields)
        )

    @app.exception_handler(StarletteHTTPException)
    async def _http(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = STATUS_CODES.get(exc.status_code, "internal_error")
        message = exc.detail if isinstance(exc.detail, str) and exc.status_code < 500 else "Request failed"
        return JSONResponse(status_code=exc.status_code, content=envelope(code, message))

    @app.exception_handler(Exception)
    async def _unexpected(_: Request, exc: Exception) -> JSONResponse:
        logger.exception("unhandled error")
        return JSONResponse(status_code=500, content=envelope("internal_error", "Something went wrong", retryable=True))
