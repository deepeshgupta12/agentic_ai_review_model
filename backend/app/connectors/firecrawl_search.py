"""Firecrawl's search API as a second discovery engine beside Brave (D72; connector firecrawl_search).

On 15 Oct 2026 Brave found three pages naming Conscient Parq and nothing on Housing.com, NoBroker or Quora. Firecrawl
searches a different index (`POST /v2/search`, results under `data.web[]` with url, title and description) and
understands `inurl:`, so it also takes the portal project-page queries (identity.queries.PROJECT_PAGE_SITES).
Results are discovery metadata only, like Brave's: a page becomes a content source only when the web reader reads it
under its host's policy. A search costs 2 credits per 10 results, rounded up; they are reserved in the Firecrawl
ledger (`firecrawl`, shared with the page renderer, FIRECRAWL_MONTHLY_CREDITS) before the request and settled with
the credits Firecrawl reports. One request per query, never repeated (a request sent again may be billed again).
"""

from __future__ import annotations

import json
import math
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any

from pymongo.database import Database

from app.config import Settings
from app.connectors.base import Connector, Page, ProviderError, QuotaExhausted
from app.connectors.brave import query_string
from app.connectors.firecrawl import JSON_TYPES, LEDGER
from app.db import utcnow
from app.sources import quota
from app.sources.http import FetchError, SafeClient
from app.sources.store import Item, normalise_url

SEARCH_API = "https://api.firecrawl.dev/v2/search"
UNKNOWN_DATE = {"status": "unknown", "value": None, "precision": None, "basis": None}


def credits_for(results: int) -> int:
    """Firecrawl's price of a search: 2 credits per 10 results, rounded up."""
    return 2 * math.ceil(results / 10)


def date_range(window_days: int, now: datetime) -> str:
    """The run's look-back as a custom date range (the `tbs` filter, month/day/year)."""
    start = now - timedelta(days=window_days)
    return f"cdr:1,cd_min:{start:%m/%d/%Y},cd_max:{now:%m/%d/%Y}"


class FirecrawlSearch(Connector):
    id = "firecrawl_search"
    supports = frozenset({"discover", "health"})

    def __init__(
        self,
        api_key: str,
        client: SafeClient,
        db: Database[dict[str, Any]],
        settings: Settings,
        now: Callable[[], datetime] = utcnow,
    ) -> None:
        self._key, self.client, self.db, self.settings, self.now = api_key, client, db, settings, now

    def discover(self, query: dict[str, Any], cursor: str | None) -> Page:
        """One page of results per query (no cursor). Raises QuotaExhausted before any request when the month's
        credits are spent, ProviderError when Firecrawl refuses or fails."""
        results = self.settings.firecrawl_search_results
        reserved = credits_for(results)
        if not quota.reserve(self.db, self.settings, LEDGER, "credits", reserved, self.now()):
            raise QuotaExhausted(LEDGER, "credits")
        body = {
            "query": query_string(query)[:500],
            "limit": results,
            "sources": ["web"],
            "country": "IN",
            "tbs": date_range(int(query["window_days"]), self.now()),
            "timeout": 60000,
        }
        try:
            response = self.client.post_json(
                SEARCH_API, body, headers={"Authorization": f"Bearer {self._key}"}, accept=JSON_TYPES
            )
        except FetchError as exc:
            raise ProviderError(
                exc.code, "Firecrawl search failed", retryable=exc.retryable, status=exc.status
            ) from exc
        if response.status == 401:
            raise ProviderError(
                "access_refused", "Firecrawl refused the API key (HTTP 401)", retryable=False, status=401
            )
        if response.status == 402:
            raise ProviderError("quota_exhausted", "Firecrawl plan credits are used up (HTTP 402)", retryable=False)
        if response.status == 429:
            raise ProviderError("rate_limited", "Firecrawl rate limit (HTTP 429)", retryable=True, status=429)
        if response.status >= 400:
            raise ProviderError(
                "provider_error",
                f"Firecrawl search returned HTTP {response.status}",
                retryable=response.status in (408, 500, 502, 503, 504),
                status=response.status,
            )
        try:
            payload = json.loads(response.body)
            data = payload.get("data") or {}
            web = data.get("web") if isinstance(data, dict) else data
        except (json.JSONDecodeError, AttributeError) as exc:
            raise ProviderError("bad_response", "Firecrawl search returned invalid JSON", retryable=True) from exc
        if payload.get("success") is False:
            raise ProviderError("provider_error", "Firecrawl reported a failed search", retryable=True)
        used = payload.get("creditsUsed")
        quota.settle(
            self.db, self.settings, LEDGER, "credits", reserved, used if isinstance(used, int) else None, self.now()
        )
        items = []
        for result in web if isinstance(web, list) else []:
            url = result.get("url") if isinstance(result, dict) else None
            if not isinstance(url, str) or not url.startswith(("http://", "https://")):
                continue
            canonical = normalise_url(url)
            title = result.get("title") or (result.get("metadata") or {}).get("title")
            items.append(
                Item(
                    connector_id=self.id,
                    native_id=canonical,
                    canonical_url=canonical,
                    source_kind="search_result",
                    capture_level="metadata_only",
                    title=title if isinstance(title, str) and title.strip() else None,
                    publication_date=dict(UNKNOWN_DATE),
                )
            )
        return Page(items=items, next_cursor=None)

    def health(self) -> dict[str, Any]:
        return {"quota": quota.usage(self.db, self.settings, LEDGER, "credits", self.now())}
