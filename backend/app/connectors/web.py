"""Reading allow-listed public pages (connector web_fetch; D33 with D40: static fetch + Trafilatura, no stealth).

Before a page is requested: its host's policy family must allow collection and be one the web reader serves
(generic web allow-list, competitor portals, official records). robots.txt is asked for every page and its verdict
logged; it blocks the fetch only where the family's policy version says `obey` (D46: the product owner set the
web families to `record_only` on 1 Oct 2026). Every redirect hop is checked the same way. A refused page
(401/403/406/451) is recorded as refused and not worked around (D33), with one exception the product owner decided:
a competitor-portal page that refuses the reader is asked for once more through Scrapfly's unblocker (D60), up to
`UNBLOCKED_PAGES_PER_RUN` pages per collection job, still public pages only (no sign-in, accounts or cookies); D61
extends this to the generic web. A page that comes back nearly empty because the browser builds its text is rendered
once through Firecrawl (D62), up to `RENDERED_PAGES_PER_RUN` pages per job.
The page's main text, title, author name and the date the markup states are kept; pages with too little text
(often script-rendered) are counted as thin rather than stored. Every decision goes to the fetch log.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

import trafilatura
from pymongo.database import Database

from app.connectors.base import Availability, Connector, ProviderError, QuotaExhausted
from app.sources import policies
from app.sources.http import FetchError, SafeClient
from app.sources.robots import RobotsCache
from app.sources.state import log_fetch
from app.sources.store import UNKNOWN_DATE, Item, normalise_url

MIN_TEXT_CHARS = 200
REFUSED = {401, 403, 406, 451}
GONE = {404, 410}
LANG_ATTR = re.compile(r"<html[^>]*\blang=[\"']?([A-Za-z]{2,3}(?:-[A-Za-z0-9]{2,8})*)", re.IGNORECASE)
LANGUAGE_TAG = re.compile(r"^[a-z]{2,3}(-[A-Za-z0-9]{2,8})*$")


@dataclass
class FetchOutcome:
    status: str  # fetched | not_allowed | robots_disallowed | refused | gone | thin | error
    url: str
    reason: str
    item: Item | None = None
    policy: dict[str, Any] | None = None
    retryable: bool = False


def _language(html: str) -> str | None:
    m = LANG_ATTR.search(html[:5000])
    if not m:
        return None
    parts = m.group(1).split("-")
    tag = "-".join([parts[0].lower(), *parts[1:]])
    return tag if LANGUAGE_TAG.match(tag) else None


# Dates only from structured markup (meta tags, JSON-LD, <time>, the URL). The default "extensive" search also reads
# free text such as "Updated on 29 September", which is not a stated publication date (found live, 30 Sep 2026).
DATE_PARAMS = {"extensive_search": False, "original_date": True}


def extract(html: str, url: str) -> dict[str, Any] | None:
    doc = trafilatura.bare_extraction(
        html,
        url=url,
        with_metadata=True,
        include_comments=True,
        include_tables=True,
        date_extraction_params=DATE_PARAMS,
    )
    if doc is None:
        return None
    data: dict[str, Any] = doc.as_dict() if hasattr(doc, "as_dict") else dict(doc)
    data["language"] = data.get("language") or _language(html)
    return data


def publication_date(value: Any) -> dict[str, Any]:
    """The date the page markup states, as an approximate day: extraction can be wrong, so never 'known'."""
    if isinstance(value, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        return {"status": "approximate", "value": f"{value}T00:00:00Z", "precision": "day", "basis": "page_markup"}
    return dict(UNKNOWN_DATE)


class WebFetch(Connector):
    id = "web_fetch"
    supports = frozenset({"fetch_item", "check_availability", "health"})

    def __init__(
        self,
        client: SafeClient,
        robots: RobotsCache,
        db: Database[dict[str, Any]],
        unblocker: Any = None,
        unblock_limit: int = 0,
        renderer: Any = None,
        render_limit: int = 0,
    ) -> None:
        self.client, self.robots, self.db = client, robots, db
        self.unblocker, self.unblock_left = unblocker, unblock_limit  # D60, D61: Scrapfly for refused pages
        self.renderer, self.render_left = renderer, render_limit  # D62: Firecrawl for pages built by JavaScript

    def _allowed(self, url: str) -> tuple[policies.Resolution, str | None]:
        resolution = policies.resolve(self.db, url)
        if resolution.family not in policies.WEB_FETCH_FAMILIES:
            return resolution, f"{resolution.host} is reached only through its own connector ({resolution.family})"
        if not resolution.may_collect:
            return resolution, resolution.reason
        return resolution, None

    def fetch(self, url: str, run_id: str | None = None) -> FetchOutcome:
        url = normalise_url(url)
        resolution, refusal = self._allowed(url)
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
        if refusal:
            log_fetch(self.db, {**entry, "outcome": "not_allowed"})
            return FetchOutcome("not_allowed", url, refusal)
        decision = self.robots.decide(url)
        entry["robots"] = decision.basis if decision.allowed else f"disallowed ({decision.basis})"
        if not decision.allowed and policies.obeys_robots(resolution.policy):
            log_fetch(self.db, {**entry, "outcome": "robots_disallowed"})
            return FetchOutcome("robots_disallowed", url, f"robots.txt: {decision.basis}")

        def check_hop(hop: str) -> None:
            if normalise_url(hop) == url:
                return
            hop_resolution, hop_refusal = self._allowed(hop)
            if hop_refusal:
                raise FetchError("redirect_not_allowed", f"redirect to a page the policy does not allow: {hop_refusal}")
            if not self.robots.decide(hop).allowed and policies.obeys_robots(hop_resolution.policy):
                raise FetchError("redirect_robots_disallowed", "redirect to a path robots.txt disallows")

        try:
            response = self.client.get(url, check_hop=check_hop)
        except FetchError as exc:
            log_fetch(self.db, {**entry, "outcome": f"error:{exc.code}", "status_code": exc.status})
            return FetchOutcome("error", url, exc.message, retryable=exc.retryable)
        entry["status_code"] = response.status
        if response.status in GONE:
            log_fetch(self.db, {**entry, "outcome": "gone"})
            return FetchOutcome("gone", url, f"HTTP {response.status}")
        if response.status in REFUSED and resolution.family in policies.UNBLOCK_FAMILIES and self.unblocker:
            log_fetch(self.db, {**entry, "outcome": "refused"})
            return self._unblocked(url, entry, resolution)
        if response.status in REFUSED or response.status >= 400:
            outcome = "refused" if response.status in REFUSED else "error"
            log_fetch(self.db, {**entry, "outcome": outcome})
            return FetchOutcome(outcome, url, f"HTTP {response.status}; not worked around")
        final_url = normalise_url(response.url)
        if final_url != url:  # every hop was checked; the page is governed by the policy where it landed
            entry["final_url"] = final_url
            resolution = self._allowed(final_url)[0]
        return self._page(response.text(), url, final_url, entry, resolution, "fetched")

    def _unblocked(self, url: str, entry: dict[str, Any], resolution: policies.Resolution) -> FetchOutcome:
        """The refused competitor page once more through Scrapfly (D60), while this job's allowance lasts."""
        if self.unblock_left <= 0:
            return FetchOutcome("refused", url, "refused; this run's allowance of pages read through Scrapfly is used")
        self.unblock_left -= 1
        attempt = {**entry, "status_code": None}
        try:
            page = self.unblocker.scrape(url)
        except QuotaExhausted:
            log_fetch(self.db, {**attempt, "outcome": "unblock_quota_exhausted"})
            return FetchOutcome("refused", url, "refused; the month's Scrapfly credits are spent")
        except ProviderError as exc:
            log_fetch(self.db, {**attempt, "outcome": f"unblock_error:{exc.code}"})
            return FetchOutcome("refused", url, f"refused; Scrapfly: {exc.code}")
        except FetchError as exc:
            log_fetch(self.db, {**attempt, "outcome": f"unblock_error:{exc.code}"[:100]})
            return FetchOutcome("error", url, exc.message, retryable=exc.retryable)
        attempt.update(status_code=page.upstream_status or None, provider_credits=page.credits)
        if page.upstream_status in GONE:
            log_fetch(self.db, {**attempt, "outcome": "gone"})
            return FetchOutcome("gone", url, f"HTTP {page.upstream_status} through Scrapfly")
        if page.upstream_status >= 400 or not page.html:
            log_fetch(self.db, {**attempt, "outcome": "unblock_refused"})
            return FetchOutcome("refused", url, f"refused even through Scrapfly (HTTP {page.upstream_status})")
        return self._page(page.html, url, url, attempt, resolution, "fetched_unblocked")

    def _rendered(
        self, url: str, final_url: str, entry: dict[str, Any], resolution: policies.Resolution
    ) -> FetchOutcome:
        """The nearly empty page once more, rendered by Firecrawl (D62), while this job's allowance lasts."""
        if self.render_left <= 0:
            return FetchOutcome(
                "thin", url, "script-rendered; this run's allowance of pages rendered by Firecrawl is used"
            )
        self.render_left -= 1
        attempt = {**entry, "status_code": None}
        try:
            page = self.renderer.render(final_url)
        except QuotaExhausted:
            log_fetch(self.db, {**attempt, "outcome": "render_quota_exhausted"})
            return FetchOutcome("thin", url, "script-rendered; the month's Firecrawl credits are spent")
        except ProviderError as exc:
            log_fetch(self.db, {**attempt, "outcome": f"render_error:{exc.code}"})
            return FetchOutcome("thin", url, f"script-rendered; Firecrawl: {exc.code}")
        except FetchError as exc:
            log_fetch(self.db, {**attempt, "outcome": f"render_error:{exc.code}"[:100]})
            return FetchOutcome("error", url, exc.message, retryable=exc.retryable)
        attempt.update(status_code=page.upstream_status or None, provider_credits=page.credits)
        if page.upstream_status in GONE:
            log_fetch(self.db, {**attempt, "outcome": "gone"})
            return FetchOutcome("gone", url, f"HTTP {page.upstream_status} through Firecrawl")
        if page.upstream_status >= 400 or not page.html:
            log_fetch(self.db, {**attempt, "outcome": "render_refused"})
            return FetchOutcome("refused", url, f"refused even through Firecrawl (HTTP {page.upstream_status})")
        return self._page(page.html, url, final_url, attempt, resolution, "fetched_rendered")

    def _page(
        self,
        html: str,
        url: str,
        final_url: str,
        entry: dict[str, Any],
        resolution: policies.Resolution,
        outcome: str,
    ) -> FetchOutcome:
        data = extract(html, final_url)
        text = (data or {}).get("text") or ""
        if len(text) < MIN_TEXT_CHARS:
            log_fetch(self.db, {**entry, "outcome": "thin"})
            if outcome != "fetched_rendered" and resolution.family in policies.UNBLOCK_FAMILIES and self.renderer:
                return self._rendered(url, final_url, entry, resolution)
            return FetchOutcome("thin", url, f"only {len(text)} characters of main text (possibly script-rendered)")
        assert data is not None
        comments = data.get("comments") or ""
        body = text + (f"\n\nComments on this page:\n{comments}" if comments else "")
        author = data.get("author")
        item = Item(
            connector_id=self.id,
            native_id=final_url,
            canonical_url=final_url,
            source_kind="forum_thread" if comments else "article",
            capture_level="full_content",
            title=data.get("title") or None,
            text=body,
            publication_date=publication_date(data.get("date")),
            language=data.get("language"),
            author={"display_name": str(author)[:200], "role": "unknown", "role_basis": "none"} if author else None,
        )
        log_fetch(self.db, {**entry, "outcome": outcome})
        return FetchOutcome("fetched", final_url, outcome, item=item, policy=resolution.policy)

    def fetch_item(self, ref: str) -> Item:
        outcome = self.fetch(ref)
        if outcome.item is None:
            raise FetchError(outcome.status, outcome.reason, retryable=outcome.retryable)
        return outcome.item

    def check_availability(self, source: dict[str, Any]) -> Availability:
        outcome = self.fetch(source["canonical_url"])
        if outcome.status == "gone":
            return Availability("gone", outcome.reason)
        if outcome.status != "fetched" or outcome.item is None:
            return Availability("unknown", f"{outcome.status}: {outcome.reason}")
        from app.identity.text import nfc, sha256_text

        same = source.get("content_sha256") == sha256_text(nfc(outcome.item.text or ""))
        return Availability("present" if same else "changed", "unchanged" if same else "content changed", outcome.item)

    def health(self) -> dict[str, Any]:
        return {"quota": {"limit": None, "used": None, "resets_at": None}}
