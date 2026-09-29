"""YouTube Data API v3 (connector youtube_data_api; docs/06 order 3; policy family youtube).

- search.list finds videos (its own quota: 100 calls a Pacific day by default); videos.list reads their
  metadata; commentThreads.list reads public comments (both from the shared 10,000-unit bucket).
- Videos are metadata only: title, channel, date and duration, with format 'unknown' (duration alone never
  makes a Short) and no transcript route. They never become spoken evidence (docs/06 media rules).
- Comments are their own text sources, parented to their video; replies are parented to their thread's top
  comment. A comment is labelled 'creator' only when the platform shows it came from the video's channel.
- Comments turned off is recorded as a fact, not an error. The API key goes in a header, never in a URL.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any

from pymongo.database import Database

from app.config import Settings
from app.connectors.base import Availability, Connector, Page, ProviderError, QuotaExhausted
from app.db import utcnow
from app.sources import quota
from app.sources.http import JSON_TYPES, FetchError, SafeClient
from app.sources.store import Item

API = "https://www.googleapis.com/youtube/v3"
DURATION = re.compile(r"^P(?:(\d+)D)?T?(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?$")
LANGUAGE_TAG = re.compile(r"^[a-z]{2,3}(-[A-Za-z0-9]{2,8})*$")


def duration_ms(value: str | None) -> int | None:
    m = DURATION.match(value or "")
    if not m or not any(m.groups()):
        return None
    days, hours, minutes, seconds = (int(g or 0) for g in m.groups())
    return (((days * 24 + hours) * 60 + minutes) * 60 + seconds) * 1000


def instant(value: str | None) -> dict[str, Any]:
    if not value:
        return {"status": "unknown", "value": None, "precision": None, "basis": None}
    return {
        "status": "known",
        "value": value.replace("+00:00", "Z"),
        "precision": "instant",
        "basis": "platform_metadata",
    }


def language(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    tag = value.split("-")[0].lower() + ("-" + "-".join(value.split("-")[1:]) if "-" in value else "")
    return tag if LANGUAGE_TAG.match(tag) else None


def watch_url(video_id: str) -> str:
    return f"https://www.youtube.com/watch?v={video_id}"


class YouTubeDataApi(Connector):
    id = "youtube_data_api"
    supports = frozenset({"discover", "fetch_item", "fetch_thread", "check_availability", "health"})

    def __init__(
        self,
        api_key: str,
        client: SafeClient,
        db: Database[dict[str, Any]],
        settings: Settings,
        now: Callable[[], datetime] = utcnow,
    ) -> None:
        self._key, self.client, self.db, self.settings, self.now = api_key, client, db, settings, now

    def _call(self, endpoint: str, params: dict[str, Any], bucket: str) -> dict[str, Any]:
        if not quota.reserve(self.db, self.settings, self.id, bucket, 1, self.now()):
            raise QuotaExhausted(self.id, bucket)
        try:
            response = self.client.get(
                f"{API}/{endpoint}", params=params, headers={"X-Goog-Api-Key": self._key}, accept=JSON_TYPES
            )
        except FetchError as exc:
            raise ProviderError(exc.code, exc.message, retryable=exc.retryable, status=exc.status) from exc
        try:
            data: dict[str, Any] = json.loads(response.body) if response.body else {}
        except json.JSONDecodeError as exc:
            raise ProviderError("bad_response", "YouTube returned invalid JSON", retryable=True) from exc
        if response.status >= 400:
            reasons = {e.get("reason") for e in (data.get("error") or {}).get("errors", []) if isinstance(e, dict)}
            if "commentsDisabled" in reasons:
                raise ProviderError(
                    "comments_disabled", "comments are turned off for this video", retryable=False, status=403
                )
            if reasons & {"quotaExceeded", "dailyLimitExceeded", "rateLimitExceeded"}:
                raise ProviderError("quota_exceeded", "YouTube quota exceeded", retryable=False, status=response.status)
            if response.status in (400, 401, 403):
                raise ProviderError(
                    "access_refused", "YouTube refused the request or the key", retryable=False, status=response.status
                )
            if response.status == 404:
                raise ProviderError("not_found", "not found on YouTube", retryable=False, status=404)
            raise ProviderError(
                "provider_error", f"YouTube returned HTTP {response.status}", retryable=False, status=response.status
            )
        return data

    def discover(self, query: dict[str, Any], cursor: str | None) -> Page:
        """One search page, then the metadata of the videos it found."""
        published_after = (self.now() - timedelta(days=int(query["window_days"]))).strftime("%Y-%m-%dT%H:%M:%SZ")
        params = {
            "part": "snippet",
            "q": query["query_text"],
            "type": "video",
            "maxResults": 25,
            "regionCode": "IN",
            "relevanceLanguage": "en",
            "publishedAfter": published_after,
            "safeSearch": "none",
        }
        if cursor:
            params["pageToken"] = cursor
        data = self._call("search", params, "search")
        ids = [
            i["id"]["videoId"]
            for i in data.get("items", [])
            if isinstance(i.get("id"), dict) and i["id"].get("videoId")
        ]
        videos = self.videos(ids)
        return Page(
            items=[item for item, _ in videos],
            next_cursor=data.get("nextPageToken"),
            attempted=2 if ids else 1,
            match_text={item.native_id: text for item, text in videos},
        )

    def videos(self, video_ids: list[str]) -> list[tuple[Item, str]]:
        """Video items with their title and description, which are used for matching and not stored."""
        if not video_ids:
            return []
        data = self._call("videos", {"part": "snippet,contentDetails", "id": ",".join(video_ids[:50])}, "units")
        return [(self._video_item(v), self.metadata_text(v)) for v in data.get("items", [])]

    def _video_item(self, video: dict[str, Any]) -> Item:
        snippet = video.get("snippet") or {}
        video_id = video["id"]
        return Item(
            connector_id=self.id,
            native_id=f"video:{video_id}",
            canonical_url=watch_url(video_id),
            source_kind="video",
            capture_level="metadata_only",
            title=snippet.get("title"),
            publication_date=instant(snippet.get("publishedAt")),
            language=language(snippet.get("defaultAudioLanguage") or snippet.get("defaultLanguage")),
            author={
                "display_name": (snippet.get("channelTitle") or None) and str(snippet["channelTitle"])[:200],
                "role": "creator",
                "role_basis": "platform_badge",
            },
            media={
                "duration_ms": duration_ms((video.get("contentDetails") or {}).get("duration")),
                "format": "unknown",
                "format_basis": "unknown",
                "access_status": "metadata_only",
                "transcript_route": None,
                "channel": {"native_id": snippet.get("channelId") or "unknown", "title": snippet.get("channelTitle")},
            },
        )

    def metadata_text(self, video: dict[str, Any]) -> str:
        """Title and description for identity matching only; not stored as content."""
        snippet = video.get("snippet") or {}
        return f"{snippet.get('title') or ''}\n\n{snippet.get('description') or ''}".strip()

    def fetch_thread(self, parent: dict[str, Any], cursor: str | None) -> Page:
        """One page of comment threads for a stored video source."""
        video_id = parent["native_id"].split(":", 1)[1]
        channel_id = ((parent.get("media") or {}).get("channel") or {}).get("native_id")
        params = {
            "part": "snippet,replies",
            "videoId": video_id,
            "maxResults": 100,
            "textFormat": "plainText",
            "order": "time",
        }
        if cursor:
            params["pageToken"] = cursor
        data = self._call("commentThreads", params, "units")
        items: list[Item] = []
        for thread in data.get("items", []):
            top = (thread.get("snippet") or {}).get("topLevelComment") or {}
            item = self._comment_item(top, video_id, channel_id, {"id": parent["id"], "revision": parent["revision"]})
            if item is None:
                continue
            items.append(item)
            for reply in (thread.get("replies") or {}).get("comments", []):
                reply_item = self._comment_item(reply, video_id, channel_id, None, parent_comment=top.get("id"))
                if reply_item is not None:
                    items.append(reply_item)
        return Page(items=items, next_cursor=data.get("nextPageToken"))

    def _comment_item(
        self,
        comment: dict[str, Any],
        video_id: str,
        channel_id: str | None,
        parent: dict[str, Any] | None,
        parent_comment: str | None = None,
    ) -> Item | None:
        snippet = comment.get("snippet") or {}
        text = (snippet.get("textDisplay") or "").strip()
        comment_id = comment.get("id")
        if not text or not comment_id:
            return None
        author_channel = (snippet.get("authorChannelId") or {}).get("value")
        is_creator = bool(channel_id and author_channel == channel_id)
        item = Item(
            connector_id=self.id,
            native_id=f"comment:{comment_id}",
            canonical_url=f"{watch_url(video_id)}&lc={comment_id}",
            source_kind="comment",
            capture_level="full_content",
            text=text,
            publication_date=instant(snippet.get("publishedAt")),
            author={
                "display_name": (snippet.get("authorDisplayName") or None) and str(snippet["authorDisplayName"])[:200],
                "role": "creator" if is_creator else "unknown",
                "role_basis": "platform_badge" if is_creator else "none",
            },
            parent=parent,
        )
        item.media = None
        if parent_comment:
            item.parent = {"native_id": f"comment:{parent_comment}"}  # resolved to a source ref when stored
        return item

    def check_availability(self, source: dict[str, Any]) -> Availability:
        kind, _, native = source["native_id"].partition(":")
        if kind == "video":
            data = self._call("videos", {"part": "snippet,contentDetails", "id": native}, "units")
            if not data.get("items"):
                return Availability("gone", "the video is no longer available")
            item = self._video_item(data["items"][0])
            same = item.title == source.get("title")
            return Availability("present" if same else "changed", "unchanged" if same else "title changed", item)
        if kind == "comment":
            data = self._call("comments", {"part": "snippet", "id": native, "textFormat": "plainText"}, "units")
            if not data.get("items"):
                return Availability("gone", "the comment is no longer available")
            return Availability("present", "present")
        return Availability("unknown", f"unrecognised native id {source['native_id']}")

    def health(self) -> dict[str, Any]:
        now = self.now()
        return {
            "quota": quota.usage(self.db, self.settings, self.id, "search", now),
            "units": quota.usage(self.db, self.settings, self.id, "units", now),
        }
