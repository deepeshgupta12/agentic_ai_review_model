"""Scrapfly's scrape API, shared by the Instagram connector (D54) and the competitor-portal fallback (D60).

One request per page: `unblocker=true`, `proxy_pool=public_residential_pool`, `country=in`, no JavaScript rendering.
Credits are reserved in one monthly ledger (`scrapfly`, `SCRAPFLY_MONTHLY_CREDITS`) before each request, so the two
uses can never spend more than the plan has together; the credits Scrapfly reports go to the caller's fetch log. The
API key is sent only to Scrapfly and never appears in an error or a log.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from pymongo.database import Database

from app.config import Settings
from app.connectors.base import ProviderError, QuotaExhausted
from app.db import utcnow
from app.sources import quota
from app.sources.http import FetchError, SafeClient

SCRAPE_API = "https://api.scrapfly.io/scrape"
LEDGER = "scrapfly"
JSON_TYPES = ("application/json",)


@dataclass
class ScrapedPage:
    upstream_status: int  # what the site answered Scrapfly
    html: str
    credits: int | None


class Scrapfly:
    def __init__(
        self,
        api_key: str,
        client: SafeClient,
        db: Database[dict[str, Any]],
        settings: Settings,
        now: Callable[[], datetime] = utcnow,
    ) -> None:
        self._key, self.client, self.db, self.settings, self.now = api_key, client, db, settings, now

    def scrape(self, url: str) -> ScrapedPage:
        """Raises QuotaExhausted before any request when the month's credits are spent, ProviderError when Scrapfly
        refuses the key or the quota, FetchError when the scrape fails."""
        cost = self.settings.scrapfly_credits_per_post
        if not quota.reserve(self.db, self.settings, LEDGER, "credits", cost, self.now()):
            raise QuotaExhausted(LEDGER, "credits")
        params = {
            "key": self._key,
            "url": url,
            "unblocker": "true",
            "proxy_pool": "public_residential_pool",
            "country": "in",
            "render_js": "false",
        }
        try:
            response = self.client.get(SCRAPE_API, params=params, accept=JSON_TYPES)
        except FetchError as exc:
            raise FetchError(exc.code, "Scrapfly request failed", retryable=exc.retryable, status=exc.status) from exc
        reported = response.headers.get("x-scrapfly-api-cost")
        credits = int(reported) if reported and reported.isdigit() else None
        if response.status in (401, 402):
            raise ProviderError(
                "access_refused", f"Scrapfly refused the request (HTTP {response.status})", retryable=False
            )
        if response.status == 429:
            raise ProviderError("quota_exhausted", "Scrapfly quota or concurrency used up", retryable=True)
        if response.status >= 400:
            reason = response.headers.get("x-scrapfly-reject-code") or f"HTTP {response.status}"
            raise FetchError("scrape_failed", f"Scrapfly could not read the page: {reason}", retryable=True)
        try:
            result = json.loads(response.body)["result"]
        except (json.JSONDecodeError, KeyError, TypeError) as exc:
            raise FetchError("bad_response", "Scrapfly returned an unexpected response", retryable=True) from exc
        return ScrapedPage(int(result.get("status_code") or 0), str(result.get("content") or ""), credits)

    def credits(self) -> dict[str, Any]:
        return quota.usage(self.db, self.settings, LEDGER, "credits", self.now())
