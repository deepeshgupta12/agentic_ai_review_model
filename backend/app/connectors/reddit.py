"""Reddit without the Reddit API (connector reddit_public; D67, D68).

Public threads and comments that name a project, found and read through PullPush, a free community archive of
Reddit with a search API and no key (`api.pullpush.io/reddit/search/submission` and `/comment`): no login, no
account, no Reddit API key. A thread PullPush has no comments for may be read once more from Reddit's own public
JSON through Scrapfly, within `REDDIT_THREADS_VIA_SCRAPFLY_PER_RUN` (0 by default: it spends Scrapfly credits).

Each post and each comment is stored as its own source (post `forum_post`, comment `comment`, the comment under its
post), so a review is always one person's words. Usernames are never kept: the author is stored without a name and
with an unknown role. Deleted, removed, moderator and bot posts are left out; the subreddit stays in the title (it is
part of the context people write in, such as r/gurgaon).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from pymongo.database import Database

from app.config import Settings
from app.connectors.base import Connector, ProviderError, QuotaExhausted
from app.sources.http import JSON_TYPES, FetchError, SafeClient
from app.sources.store import Item, normalise_url

ID = "reddit_public"
PULLPUSH = "https://api.pullpush.io/reddit/search"
SKIPPED_AUTHORS = {"[deleted]", "automoderator"}
SKIPPED_TEXTS = {"[deleted]", "[removed]", ""}


@dataclass
class Thread:
    post: dict[str, Any]
    comments: list[dict[str, Any]] = field(default_factory=list)
    via: str = "pullpush"


def _skip(entry: dict[str, Any]) -> bool:
    author = str(entry.get("author") or "").lower()
    text = str(entry.get("body") if "body" in entry else entry.get("selftext") or entry.get("title") or "").strip()
    return (
        author in SKIPPED_AUTHORS
        or author.endswith("bot")
        or entry.get("distinguished") == "moderator"
        or text.lower() in SKIPPED_TEXTS
        or bool(entry.get("removed_by_category"))
    )


def _when(entry: dict[str, Any]) -> dict[str, Any]:
    try:
        stamp = datetime.fromtimestamp(float(entry["created_utc"]), UTC)
    except (KeyError, TypeError, ValueError):
        return {"status": "unknown", "value": None, "precision": None, "basis": None}
    return {
        "status": "known",
        "value": stamp.isoformat().replace("+00:00", "Z"),
        "precision": "instant",
        "basis": "platform_metadata",
    }


def _url(entry: dict[str, Any]) -> str:
    return normalise_url("https://www.reddit.com" + str(entry.get("permalink") or ""))


AUTHOR = {"display_name": None, "role": "unknown", "role_basis": "none"}


def post_item(post: dict[str, Any]) -> Item:
    title = " ".join(str(post.get("title") or "").split())
    body = str(post.get("selftext") or "").strip()
    body = "" if body.lower() in SKIPPED_TEXTS else body
    return Item(
        connector_id=ID,
        native_id=f"t3_{post['id']}",
        canonical_url=_url(post),
        source_kind="forum_post",
        capture_level="full_content",
        title=f"{title} (r/{post.get('subreddit')})" if post.get("subreddit") else title,
        text=f"{title}\n\n{body}" if body else title,
        publication_date=_when(post),
        language=None,
        author=dict(AUTHOR),
    )


def comment_item(comment: dict[str, Any]) -> Item:
    link = str(comment.get("link_id") or "")
    return Item(
        connector_id=ID,
        native_id=f"t1_{comment['id']}",
        canonical_url=_url(comment),
        source_kind="comment",
        capture_level="full_content",
        title=None,
        text=str(comment.get("body") or "").strip(),
        publication_date=_when(comment),
        language=None,
        author=dict(AUTHOR),
        parent={"native_id": link} if link.startswith("t3_") else None,
    )


def flatten_listing(data: Any) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    """Reddit's own thread JSON ([post listing, comment listing]) as the post and every comment, replies included."""
    if not isinstance(data, list) or len(data) < 2:
        return None, []
    posts = [c.get("data") for c in (data[0].get("data") or {}).get("children", []) if c.get("kind") == "t3"]
    comments: list[dict[str, Any]] = []

    def walk(listing: Any) -> None:
        if not isinstance(listing, dict):
            return
        for child in (listing.get("data") or {}).get("children", []):
            if child.get("kind") != "t1":
                continue
            entry = child.get("data") or {}
            comments.append(entry)
            walk(entry.get("replies"))

    walk(data[1])
    return (posts[0] if posts else None), comments


class RedditPublic(Connector):
    id = ID
    supports = frozenset({"discover", "fetch_thread", "health"})

    def __init__(
        self, client: SafeClient, db: Database[dict[str, Any]], settings: Settings, scrapfly: Any = None
    ) -> None:
        self.client, self.db, self.settings, self.scrapfly = client, db, settings, scrapfly
        self.scrapfly_left = settings.reddit_threads_via_scrapfly_per_run if scrapfly is not None else 0

    def _search(self, kind: str, params: dict[str, Any]) -> list[dict[str, Any]]:
        try:
            response = self.client.get(f"{PULLPUSH}/{kind}/", params=params, accept=JSON_TYPES)
        except FetchError as exc:
            raise ProviderError(exc.code, f"PullPush {kind} search failed", retryable=exc.retryable) from exc
        if response.status == 429:
            raise ProviderError("rate_limited", "PullPush rate limit (HTTP 429)", retryable=True)
        if response.status >= 400:
            raise ProviderError("provider_error", f"PullPush answered HTTP {response.status}", retryable=True)
        try:
            data = json.loads(response.body).get("data") or []
        except (ValueError, AttributeError) as exc:
            raise ProviderError("bad_response", "PullPush returned an unexpected response", retryable=True) from exc
        return [d for d in data if isinstance(d, dict) and d.get("id")]

    def posts_naming(self, name: str, after: datetime, size: int) -> list[dict[str, Any]]:
        """Posts whose title or text contains the quoted name, newest first, since `after`."""
        params = {"q": f'"{name}"', "after": int(after.timestamp()), "size": size, "sort": "desc"}
        return [p for p in self._search("submission", params) if not _skip(p)]

    def comments_naming(self, name: str, after: datetime, size: int) -> list[dict[str, Any]]:
        params = {"q": f'"{name}"', "after": int(after.timestamp()), "size": size, "sort": "desc"}
        return [c for c in self._search("comment", params) if not _skip(c)]

    def post(self, post_id: str) -> dict[str, Any] | None:
        found = self._search("submission", {"ids": post_id})
        return found[0] if found else None

    def thread(self, post: dict[str, Any], size: int) -> Thread:
        """A post with its comments: from PullPush, or (when PullPush has none and the allowance lasts) from Reddit's
        public JSON through Scrapfly."""
        comments = [c for c in self._search("comment", {"link_id": post["id"], "size": size}) if not _skip(c)]
        if comments or self.scrapfly_left <= 0 or not post.get("num_comments"):
            return Thread(post, comments)
        self.scrapfly_left -= 1
        try:
            page = self.scrapfly.scrape(f"https://www.reddit.com/comments/{post['id']}.json")
        except (QuotaExhausted, ProviderError, FetchError):
            return Thread(post, comments)
        try:
            fresh, everything = flatten_listing(json.loads(page.html or "null"))
        except ValueError:
            return Thread(post, comments)
        return Thread(fresh or post, [c for c in everything if c.get("id") and not _skip(c)], via="scrapfly")

    def health(self) -> dict[str, Any]:
        return {"quota": {"limit": None, "used": None, "resets_at": None}, "source": "PullPush archive"}
