"""Provider webhooks (receiveWebhook in contracts/v1/routes.json). No webhook provider is configured in this release
(the paid listening provider stays access_pending, docs/06), so no signature can be verified and every call is
refused with 401; nothing is stored. A provider is added here with its signature check, replay window and event ID."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body

from app.errors import ApiError

router = APIRouter(prefix="/v1", tags=["webhooks"])


@router.post(
    "/webhooks/{provider}",
    operation_id="receiveWebhook",
    summary="Provider webhook; verified signature, replay window and event ID",
    status_code=202,
)
def receive_webhook(provider: str, body: Any = Body(default=None)) -> dict[str, Any]:
    raise ApiError(401, "unauthenticated", f"No webhook is configured for {provider[:40]!r}; nothing was stored")
