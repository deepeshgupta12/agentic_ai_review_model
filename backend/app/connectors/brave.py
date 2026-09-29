"""Brave Search API (web search) for discovery (docs/06 order 1; connector brave_search).

Results are discovery metadata only: a URL, a title and the page age Brave reports. They never become
evidence; a page becomes a content source only if the web fetcher reads it under its host's policy.
Pagination follows `query.more_results_available` (offset 0-9, 20 results a page). Each request reserves one
unit of the monthly quota first.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

from pymongo.database import Database

from app.config import Settings
from app.connectors.base import Connector, Page, ProviderError, QuotaExhausted
from app.db import utcnow
from app.sources import quota
from app.sources.http import JSON_TYPES, FetchError, SafeClient
from app.sources.store import Item, normalise_url

ENDPOINT = "https://api.search.brave.com/res/v1/web/search"
LANGUAGE_TAG = re.compile(r"^[a-z]{2,3}(-[A-Za-z0-9]{2,8})*$")
MAX_OFFSET = 9
PAGE_SIZE = 20


def query_string(query: dict[str, Any]) -> str:
    """The plan's query text with its exclusions as quoted minus terms."""
    exclusions = " ".join(f'-"{term}"' for term in query.get("exclusions", []) if term.strip())
    return f"{query['query_text']} {exclusions}".strip()


def freshness(window_days: int, now: datetime) -> str:
    start = (now - timedelta(days=window_days)).date().isoformat()
    return f"{start}to{now.date().isoformat()}"


def page_age(result: dict[str, Any]) -> dict[str, Any]:
    """Brave's page_age is its own estimate: kept as an approximate day, never as a known publication date."""
    raw = result.get("page_age")
    if isinstance(raw, str):
        try:
            when = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            when = None
        if when is not None:
            if when.tzinfo is None:
                when = when.replace(tzinfo=UTC)
            return {
                "status": "approximate",
                "value": when.isoformat().replace("+00:00", "Z"),
                "precision": "day",
                "basis": "platform_metadata",
            }
    return {"status": "unknown", "value": None, "precision": None, "basis": None}


class BraveSearch(Connector):
    id = "brave_search"
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
        offset = int(cursor or 0)
        if not quota.reserve(self.db, self.settings, self.id, "requests", 1, self.now()):
            raise QuotaExhausted(self.id, "requests")
        params = {
            "q": query_string(query),
            "count": PAGE_SIZE,
            "offset": offset,
            "country": "IN",
            "search_lang": "en",
            "safesearch": "moderate",
            "freshness": freshness(int(query["window_days"]), self.now()),
        }
        try:
            response = self.client.get(
                ENDPOINT,
                params=params,
                headers={"X-Subscription-Token": self._key, "Accept": "application/json"},
                accept=JSON_TYPES,
            )
        except FetchError as exc:
            raise ProviderError(exc.code, exc.message, retryable=exc.retryable, status=exc.status) from exc
        if response.status in (401, 403):
            raise ProviderError("access_refused", "Brave refused the API key", retryable=False, status=response.status)
        if response.status >= 400:
            raise ProviderError(
                "provider_error", f"Brave returned HTTP {response.status}", retryable=False, status=response.status
            )
        try:
            data = json.loads(response.body)
        except json.JSONDecodeError as exc:
            raise ProviderError("bad_response", "Brave returned invalid JSON", retryable=True) from exc
        items = []
        for result in (data.get("web") or {}).get("results") or []:
            url = result.get("url")
            if not isinstance(url, str) or not url.startswith(("http://", "https://")):
                continue
            canonical = normalise_url(url)
            items.append(
                Item(
                    connector_id=self.id,
                    native_id=canonical,
                    canonical_url=canonical,
                    source_kind="search_result",
                    capture_level="metadata_only",
                    title=(result.get("title") or None),
                    publication_date=page_age(result),
                    language=language
                    if isinstance(language := result.get("language"), str) and LANGUAGE_TAG.match(language)
                    else None,
                )
            )
        more = bool((data.get("query") or {}).get("more_results_available"))
        last_offset = min(MAX_OFFSET, self.settings.brave_pages_per_query - 1)
        return Page(items=items, next_cursor=str(offset + 1) if more and offset < last_offset else None)

    def health(self) -> dict[str, Any]:
        return {"quota": quota.usage(self.db, self.settings, self.id, "requests", self.now())}
