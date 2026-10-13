"""Google Alerts by RSS as the free listening source (Step 08; connector `google_alerts`, policy `google_alerts`;
D56).

The product owner creates one alert per project in their Google account (delivery: RSS feed) and stores the feed
addresses in `GOOGLE_ALERTS_FEEDS` (space- or comma-separated; they work like private links, so they are kept with
the credentials and never logged in full). A run reads the feeds whose title ("Google Alert - <query>") names the
project or one of its approved aliases. Each entry is a mention Google found: its title, the address of the page
(taken out of Google's redirect link) and when Google found it. Entries are discovery metadata, like Brave hits:
they are stored as `search_result` items under the policy of the page they point to, and pages on allow-listed
hosts are then read by the web reader under the usual rules. Feed text is never evidence.

Alerts list new mentions only, so this source matters most for refreshes (Step 13); the first run finds what
Google indexed since the alert was made. robots.txt is asked and recorded for every feed read: google.com disallows
/alerts/ for crawlers, and a subscriber's feed reader is not a crawler, so the google_alerts policy records it
without enforcing it (D46).
"""

from __future__ import annotations

import html as html_lib
import re
import xml.etree.ElementTree as ET  # parses only Google's own feed, size-capped by the safe client
from datetime import UTC, datetime
from typing import Any
from urllib.parse import parse_qs, urlsplit

from pymongo.database import Database

from app.connectors.base import Connector, ProviderError
from app.identity.text import normalise_text
from app.sources import policies
from app.sources.http import FetchError, SafeClient
from app.sources.robots import RobotsCache
from app.sources.state import log_fetch
from app.sources.store import Item, normalise_url

ID = "google_alerts"
FAMILY = "google_alerts"
ATOM = "{http://www.w3.org/2005/Atom}"
FEED_PATH = re.compile(r"^https://(www\.)?google\.com/alerts/feeds/\d+/\d+$")
FEED_TYPES = ("application/atom+xml", "application/rss+xml", "application/xml", "text/xml")
TAG = re.compile(r"<[^>]+>")


def feed_list(raw: str | None) -> list[str]:
    """The configured feed addresses, in order, without duplicates; anything that is not an alert feed is ignored."""
    found = [part.strip() for part in re.split(r"[\s,]+", raw or "") if part.strip()]
    return list(dict.fromkeys(url for url in found if FEED_PATH.match(url)))


def redacted(url: str) -> str:
    return re.sub(r"/alerts/feeds/.*$", "/alerts/feeds/<private>", url)


def _text(node: ET.Element | None) -> str:
    raw = node.text if node is not None and node.text else ""
    return " ".join(html_lib.unescape(TAG.sub("", html_lib.unescape(raw))).split())


def target_of(link: str) -> str | None:
    """The page an alert points to: Google wraps it as https://www.google.com/url?...&url=<page>&..."""
    parts = urlsplit(link)
    if parts.hostname and parts.hostname.endswith("google.com") and parts.path == "/url":
        values = parse_qs(parts.query).get("url") or parse_qs(parts.query).get("q") or []
        link = values[0] if values else ""
    return normalise_url(link) if link.startswith(("http://", "https://")) else None


def parse_feed(body: bytes) -> tuple[str, list[dict[str, Any]]]:
    """(feed title, entries as {title, url, found_at}) from an alert's Atom feed."""
    try:
        root = ET.fromstring(body)  # noqa: S314 - see the import note
    except ET.ParseError as exc:
        raise FetchError("bad_feed", "the feed is not valid XML") from exc
    title = _text(root.find(f"{ATOM}title"))
    entries = []
    for entry in root.findall(f"{ATOM}entry"):
        link = entry.find(f"{ATOM}link")
        url = target_of(link.get("href", "")) if link is not None else None
        if url is None:
            continue
        raw_when = (entry.findtext(f"{ATOM}published") or entry.findtext(f"{ATOM}updated") or "").strip()
        try:
            when = datetime.fromisoformat(raw_when.replace("Z", "+00:00")) if raw_when else None
        except ValueError:
            when = None
        entries.append({"title": _text(entry.find(f"{ATOM}title")) or None, "url": url, "found_at": when})
    return title, entries


def names_project(feed_title: str, names: list[str]) -> bool:
    query = normalise_text(feed_title.removeprefix("Google Alert - "))
    return any(name and name in query for name in names)


class GoogleAlerts(Connector):
    id = ID
    supports = frozenset({"health"})  # read per project with `mentions`, not by query

    def __init__(self, feeds: list[str], client: SafeClient, robots: RobotsCache, db: Database[dict[str, Any]]) -> None:
        self.feeds, self.client, self.robots, self.db = feeds, client, robots, db
        self._read: dict[str, tuple[str, list[dict[str, Any]]]] = {}

    def read_feed(self, url: str, run_id: str | None = None) -> tuple[str, list[dict[str, Any]]]:
        if url in self._read:
            return self._read[url]
        resolution = policies.resolve(self.db, url)
        entry: dict[str, Any] = {
            "connector_id": self.id,
            "url": redacted(url),
            "host": resolution.host,
            "family": resolution.family,
            "policy_version": resolution.policy["policy_version"] if resolution.policy else None,
            "robots": None,
            "status_code": None,
            "run_id": run_id,
        }
        if resolution.family != FAMILY or not resolution.may_collect:
            log_fetch(self.db, {**entry, "outcome": "not_allowed"})
            raise ProviderError("not_allowed", f"alert feeds are not allowed by the {FAMILY} policy", retryable=False)
        decision = self.robots.decide(url)
        entry["robots"] = decision.basis if decision.allowed else f"disallowed ({decision.basis})"
        if not decision.allowed and policies.obeys_robots(resolution.policy):
            log_fetch(self.db, {**entry, "outcome": "robots_disallowed"})
            raise ProviderError("robots_disallowed", "robots.txt disallows the feed", retryable=False)
        try:
            response = self.client.get(url, accept=FEED_TYPES)
        except FetchError as exc:
            log_fetch(self.db, {**entry, "outcome": f"error:{exc.code}", "status_code": exc.status})
            raise ProviderError(exc.code, "the alert feed could not be read", retryable=exc.retryable) from exc
        entry["status_code"] = response.status
        if response.status >= 400:
            log_fetch(self.db, {**entry, "outcome": "refused" if response.status in (401, 403, 404) else "error"})
            raise ProviderError("feed_refused", f"HTTP {response.status} for an alert feed", retryable=False)
        title, entries = parse_feed(response.body)
        log_fetch(self.db, {**entry, "outcome": "fetched"})
        self._read[url] = (title, entries)
        return title, entries

    def mentions(self, names: list[str], run_id: str | None = None) -> tuple[list[Item], dict[str, int]]:
        """Discovery items from the feeds whose alert names the project; counts of what was seen."""
        counts: dict[str, int] = {}
        items: dict[str, Item] = {}
        for url in self.feeds:
            title, entries = self.read_feed(url, run_id)
            if not names_project(title, names):
                counts["feeds_for_other_projects"] = counts.get("feeds_for_other_projects", 0) + 1
                continue
            counts["feeds_read"] = counts.get("feeds_read", 0) + 1
            for entry in entries:
                when = entry["found_at"]
                items.setdefault(
                    entry["url"],
                    Item(
                        connector_id=self.id,
                        native_id=entry["url"],
                        canonical_url=entry["url"],
                        source_kind="search_result",
                        capture_level="metadata_only",
                        title=entry["title"],
                        publication_date={  # when Google found it: never the page's own date
                            "status": "approximate" if when else "unknown",
                            "value": when.astimezone(UTC) if when else None,
                            "precision": "day" if when else None,
                            "basis": "platform_metadata" if when else None,
                        },
                    ),
                )
        return list(items.values()), counts

    def health(self) -> dict[str, Any]:
        return {"feeds_configured": len(self.feeds), "quota": None}
