"""Instagram public posts through Scrapfly (Step 08; connector `instagram_public`, policy family `instagram_public`;
D54).

Discovery: Brave Search, restricted to instagram.com, with the project's first query texts, finds public post and
reel addresses (/p/<code>/, /reel/<code>/). Brave's own quota applies.

Reading: each post page is fetched once per run through Scrapfly's scrape API with its unblocker and residential
proxy pool, as the product owner accepted in D54. No sign-in, cookies, accounts or private content; a page that is
gated for logged-out visitors is recorded and skipped. The logged-out page embeds the post as JSON
(`<script type="application/json" data-sjs>`, method checked against Scrapfly's guide of 1 Oct 2026): the backend
takes the caption, the author's username (minimal author metadata, no profile) and the post time. Comments need a
rendered page and more credits, so this version does not read them.

Costs: every request reserves SCRAPFLY_CREDITS_PER_POST credits in a monthly ledger (SCRAPFLY_MONTHLY_CREDITS; the
free plan has 1,000) before it is made, and a run reads at most INSTAGRAM_POSTS_PER_PROJECT posts per project. The
credits Scrapfly reports for each request go to the fetch log. robots.txt is asked and recorded for every page;
the instagram_public policy says whether it is enforced (D46). The API key is sent only to Scrapfly and never logged.
"""

from __future__ import annotations

import html as html_lib
import json
import re
from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from typing import Any

from pymongo.database import Database

from app.config import Settings
from app.connectors.base import Availability, Connector, Page, ProviderError, QuotaExhausted
from app.db import utcnow
from app.sources import policies, quota
from app.sources.http import FetchError, SafeClient
from app.sources.robots import RobotsCache
from app.sources.state import log_fetch
from app.sources.store import Item

ID = "instagram_public"
FAMILY = "instagram_public"
SCRAPE_API = "https://api.scrapfly.io/scrape"
POST_PATH = re.compile(r"^https?://(?:www\.)?instagram\.com/(p|reel|reels)/([A-Za-z0-9_-]{5,40})/?", re.IGNORECASE)
SJS = re.compile(r'<script type="application/json"[^>]*data-sjs[^>]*>(.*?)</script>', re.DOTALL)
REFUSED = {401, 403, 451}
GONE = {404, 410}
JSON_TYPES = ("application/json",)


def post_url(url: str) -> tuple[str, str] | None:
    """(canonical address, shortcode) of a public post or reel, or None for any other Instagram page."""
    match = POST_PATH.match(url.strip())
    if not match:
        return None
    kind = "reel" if match.group(1).lower().startswith("reel") else "p"
    return f"https://www.instagram.com/{kind}/{match.group(2)}/", match.group(2)


def _walk(value: Any) -> Iterator[dict[str, Any]]:
    if isinstance(value, dict):
        yield value
        for item in value.values():
            yield from _walk(item)
    elif isinstance(value, list):
        for item in value:
            yield from _walk(item)


def parse_post(page: str, shortcode: str) -> dict[str, Any] | None:
    """The post object the logged-out page embeds for this shortcode, or None (gated, removed or a new layout)."""
    for block in SJS.findall(page):
        try:
            data = json.loads(html_lib.unescape(block) if block.lstrip().startswith("&") else block)
        except json.JSONDecodeError:
            continue
        for node in _walk(data):
            if node.get("code") == shortcode and "taken_at" in node:
                return node
    return None


def _text(post: dict[str, Any]) -> str | None:
    caption = post.get("caption")
    text = caption.get("text") if isinstance(caption, dict) else None
    return " ".join(text.split()) if isinstance(text, str) and text.strip() else None


class InstagramPublic(Connector):
    id = ID
    supports = frozenset({"discover", "fetch_item", "check_availability", "health"})

    def __init__(
        self,
        api_key: str,
        client: SafeClient,
        robots: RobotsCache,
        db: Database[dict[str, Any]],
        settings: Settings,
        brave: Connector | None,
        now: Callable[[], datetime] = utcnow,
    ) -> None:
        self._key, self.client, self.robots, self.db = api_key, client, robots, db
        self.settings, self.brave, self.now = settings, brave, now

    def discover(self, query: dict[str, Any], cursor: str | None) -> Page:
        """Post and reel addresses for one query, from Brave restricted to instagram.com (metadata only)."""
        if self.brave is None:
            raise ProviderError("access_pending", "discovery needs the Brave Search key", retryable=False)
        page = self.brave.discover({**query, "query_text": f"site:instagram.com {query['query_text']}"}, cursor)
        items, skipped = [], 0
        for hit in page.items:
            found = post_url(hit.canonical_url)
            if found is None:
                skipped += 1
                continue
            items.append(
                Item(
                    connector_id=self.id,
                    native_id=found[1],
                    canonical_url=found[0],
                    source_kind="search_result",
                    capture_level="metadata_only",
                    title=hit.title,
                    publication_date=hit.publication_date,
                )
            )
        return Page(items=items, next_cursor=page.next_cursor, skipped={"not_a_post": skipped} if skipped else {})

    def fetch_item(self, ref: str, run_id: str | None = None) -> Item:
        """Read one public post through Scrapfly. `ref` is the post address or its shortcode."""
        found = post_url(ref) or post_url(f"https://www.instagram.com/p/{ref}/")
        if found is None:
            raise FetchError("not_a_post", "not an Instagram post or reel address")
        url, shortcode = found
        resolution = policies.resolve(self.db, url)
        entry: dict[str, Any] = {
            "connector_id": self.id,
            "url": url,
            "host": resolution.host,
            "family": resolution.family,
            "policy_version": resolution.policy["policy_version"] if resolution.policy else None,
            "robots": None,
            "status_code": None,
            "run_id": run_id,
        }
        if resolution.family != FAMILY or not resolution.may_collect:
            log_fetch(self.db, {**entry, "outcome": "not_allowed"})
            raise FetchError("not_allowed", f"{url} is not allowed by the {FAMILY} policy")
        decision = self.robots.decide(url)
        entry["robots"] = decision.basis if decision.allowed else f"disallowed ({decision.basis})"
        if not decision.allowed and policies.obeys_robots(resolution.policy):
            log_fetch(self.db, {**entry, "outcome": "robots_disallowed"})
            raise FetchError("robots_disallowed", f"robots.txt: {decision.basis}")
        if not quota.reserve(
            self.db, self.settings, self.id, "credits", self.settings.scrapfly_credits_per_post, self.now()
        ):
            log_fetch(self.db, {**entry, "outcome": "quota_exhausted"})
            raise QuotaExhausted(self.id, "credits")
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
            log_fetch(self.db, {**entry, "outcome": f"error:{exc.code}", "status_code": exc.status})
            raise FetchError(exc.code, "Scrapfly request failed", retryable=exc.retryable, status=exc.status) from exc
        cost = response.headers.get("x-scrapfly-api-cost")
        entry["provider_credits"] = int(cost) if cost and cost.isdigit() else None
        if response.status in (401, 402):
            log_fetch(self.db, {**entry, "outcome": "provider_refused", "status_code": response.status})
            raise ProviderError(
                "access_refused", f"Scrapfly refused the request (HTTP {response.status})", retryable=False
            )
        if response.status == 429:
            log_fetch(self.db, {**entry, "outcome": "provider_quota", "status_code": response.status})
            raise ProviderError("quota_exhausted", "Scrapfly quota or concurrency used up", retryable=True)
        if response.status >= 400:
            reason = response.headers.get("x-scrapfly-reject-code") or f"HTTP {response.status}"
            log_fetch(self.db, {**entry, "outcome": f"error:{reason}"[:100], "status_code": response.status})
            raise FetchError("scrape_failed", f"Scrapfly could not read the page: {reason}", retryable=True)
        try:
            result = json.loads(response.body)["result"]
        except (json.JSONDecodeError, KeyError, TypeError) as exc:
            log_fetch(self.db, {**entry, "outcome": "error:bad_response"})
            raise FetchError("bad_response", "Scrapfly returned an unexpected response", retryable=True) from exc
        upstream = int(result.get("status_code") or 0)
        entry["status_code"] = upstream or None
        if upstream in GONE:
            log_fetch(self.db, {**entry, "outcome": "gone"})
            raise FetchError("gone", f"Instagram returned HTTP {upstream}", status=upstream)
        if upstream in REFUSED or upstream >= 400:
            log_fetch(self.db, {**entry, "outcome": "refused"})
            raise FetchError(
                "refused", f"Instagram returned HTTP {upstream}; not worked around further", status=upstream
            )
        post = parse_post(str(result.get("content") or ""), shortcode)
        text = _text(post) if post else None
        if post is None or text is None:
            log_fetch(self.db, {**entry, "outcome": "thin"})
            raise FetchError(
                "no_public_post", "no public caption on the logged-out page (gated, removed or new layout)"
            )
        log_fetch(self.db, {**entry, "outcome": "fetched"})
        return self.item_for(url, post, text)

    def item_for(self, url: str, post: dict[str, Any], text: str) -> Item:
        taken = post.get("taken_at")
        when = datetime.fromtimestamp(int(taken), tz=UTC) if isinstance(taken, int | float) and taken > 0 else None
        user = post.get("user") or post.get("owner") or {}
        username = user.get("username") if isinstance(user, dict) else None
        reel = "/reel/" in url
        return Item(
            connector_id=self.id,
            native_id=str(post.get("code")),
            canonical_url=url,
            source_kind="forum_post",  # a public post by one author; a reel's caption is its author's text
            capture_level="full_content",
            title=f"Instagram {'reel' if reel else 'post'} by {username}"
            if username
            else f"Instagram {'reel' if reel else 'post'}",
            text=text,
            publication_date={
                "status": "known" if when else "unknown",
                "value": when,
                "precision": "instant" if when else None,
                "basis": "platform_metadata" if when else None,
            },
            author={"display_name": str(username)[:200], "role": "unknown", "role_basis": "none"} if username else None,
        )

    def check_availability(self, source: dict[str, Any]) -> Availability:
        from app.identity.text import nfc, sha256_text

        try:
            item = self.fetch_item(source["canonical_url"])
        except FetchError as exc:
            if exc.code == "gone":
                return Availability("gone", exc.message)
            return Availability("unknown", f"{exc.code}: {exc.message}")
        except ProviderError as exc:
            return Availability("unknown", f"{exc.code}: {exc.message}")
        same = source.get("content_sha256") == sha256_text(nfc(item.text or ""))
        return Availability("present" if same else "changed", "unchanged" if same else "caption changed", item)

    def health(self) -> dict[str, Any]:
        return {"quota": quota.usage(self.db, self.settings, self.id, "credits", self.now())}
