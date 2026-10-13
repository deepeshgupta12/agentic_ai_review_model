"""Firecrawl's scrape API, used by the web reader for pages that are empty without JavaScript (D62).

The local reader fetches the page's HTML as served; many portals and builder sites build their text in the browser,
so the reader finds almost nothing ("thin"). Such a page of a web family is asked for once more through Firecrawl
(`POST /v2/scrape`, browser-rendered, `rawHtml`, proxy `auto`, location India), and the rendered HTML goes through the
same extraction as any page. Pages that refuse the reader go to Scrapfly instead (D60, D61). Credits are reserved in
a monthly ledger (`firecrawl`, `FIRECRAWL_MONTHLY_CREDITS`) before each request; the credits Firecrawl reports go to
the fetch log. The API key is sent only to Firecrawl and never appears in an error or a log.
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

SCRAPE_API = "https://api.firecrawl.dev/v2/scrape"
LEDGER = "firecrawl"
JSON_TYPES = ("application/json",)


@dataclass
class RenderedPage:
    upstream_status: int
    html: str
    credits: int | None


class Firecrawl:
    def __init__(
        self,
        api_key: str,
        client: SafeClient,
        db: Database[dict[str, Any]],
        settings: Settings,
        now: Callable[[], datetime] = utcnow,
    ) -> None:
        self._key, self.client, self.db, self.settings, self.now = api_key, client, db, settings, now

    def render(self, url: str) -> RenderedPage:
        """Raises QuotaExhausted before any request when the month's credits are spent, ProviderError when Firecrawl
        refuses the key or the plan, FetchError when the scrape fails."""
        if not quota.reserve(
            self.db, self.settings, LEDGER, "credits", self.settings.firecrawl_credits_per_page, self.now()
        ):
            raise QuotaExhausted(LEDGER, "credits")
        body = {
            "url": url,
            "formats": ["rawHtml"],
            "onlyMainContent": False,
            "proxy": "auto",
            "timeout": 60000,
            "location": {"country": "IN"},
        }
        try:
            response = self.client.post_json(
                SCRAPE_API, body, headers={"Authorization": f"Bearer {self._key}"}, accept=JSON_TYPES
            )
        except FetchError as exc:
            raise FetchError(exc.code, "Firecrawl request failed", retryable=exc.retryable, status=exc.status) from exc
        if response.status == 401:
            raise ProviderError("access_refused", "Firecrawl refused the API key (HTTP 401)", retryable=False)
        if response.status == 402:
            raise ProviderError("quota_exhausted", "Firecrawl plan credits are used up (HTTP 402)", retryable=False)
        if response.status == 429:
            raise ProviderError("rate_limited", "Firecrawl rate limit (HTTP 429)", retryable=True)
        if response.status >= 400:
            raise FetchError(
                "render_failed", f"Firecrawl could not render the page (HTTP {response.status})", retryable=True
            )
        try:
            payload = json.loads(response.body)
            data = payload["data"]
        except (json.JSONDecodeError, KeyError, TypeError) as exc:
            raise FetchError("bad_response", "Firecrawl returned an unexpected response", retryable=True) from exc
        if not payload.get("success", True):
            raise FetchError("render_failed", "Firecrawl reported a failed scrape", retryable=True)
        used = payload.get("creditsUsed")
        status = int(((data.get("metadata") or {}).get("statusCode")) or 0)
        return RenderedPage(
            status, str(data.get("rawHtml") or data.get("html") or ""), used if isinstance(used, int) else None
        )

    def credits(self) -> dict[str, Any]:
        return quota.usage(self.db, self.settings, LEDGER, "credits", self.now())
