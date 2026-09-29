"""Provider quota ledgers (Step 05.5). A call reserves its cost before it is made; the reservation is atomic across
workers, so a quota is never overspent. Windows follow each provider's own reset:
- Brave Search: calendar month (UTC), `brave_monthly_queries` requests;
- YouTube Data API: day in Pacific Time; `search` (100 calls/day by default) and `units` (10,000/day) are
  separate buckets, as Google counts them separately.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from pymongo import ReturnDocument
from pymongo.database import Database
from pymongo.errors import DuplicateKeyError

from app.config import Settings

COLLECTION = "ai_connector_quota"
PACIFIC = ZoneInfo("America/Los_Angeles")


@dataclass
class Bucket:
    connector_id: str
    name: str
    limit: int
    window_start: datetime
    window_end: datetime

    @property
    def key(self) -> str:
        return f"{self.connector_id}:{self.name}:{self.window_start.date().isoformat()}"


def _month(now: datetime) -> tuple[datetime, datetime]:
    start = now.astimezone(UTC).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    end = (start + timedelta(days=32)).replace(day=1)
    return start, end


def _pacific_day(now: datetime) -> tuple[datetime, datetime]:
    local = now.astimezone(PACIFIC)
    start = local.replace(hour=0, minute=0, second=0, microsecond=0)
    end = (start + timedelta(days=1, hours=1)).replace(hour=0)  # safe across daylight-saving changes
    return start.astimezone(UTC), end.astimezone(UTC)


def bucket(settings: Settings, connector_id: str, name: str, now: datetime) -> Bucket:
    if connector_id == "brave_search":
        start, end = _month(now)
        return Bucket(connector_id, name, settings.brave_monthly_queries, start, end)
    if connector_id == "youtube_data_api":
        start, end = _pacific_day(now)
        limit = settings.youtube_daily_searches if name == "search" else settings.youtube_daily_units
        return Bucket(connector_id, name, limit, start, end)
    raise KeyError(f"no quota rules for {connector_id}")


def reserve(
    db: Database[dict[str, Any]], settings: Settings, connector_id: str, name: str, cost: int, now: datetime
) -> bool:
    """Reserve `cost` in the current window. False when the window has too little left."""
    b = bucket(settings, connector_id, name, now)
    if cost > b.limit:
        return False
    try:
        db[COLLECTION].update_one(
            {"_id": b.key},
            {
                "$setOnInsert": {
                    "connector_id": connector_id,
                    "bucket": name,
                    "window_start": b.window_start,
                    "window_end": b.window_end,
                    "limit": b.limit,
                    "used": 0,
                }
            },
            upsert=True,
        )
    except DuplicateKeyError:
        pass  # another worker created the window first
    updated = db[COLLECTION].find_one_and_update(
        {"_id": b.key, "$expr": {"$lte": [{"$add": ["$used", cost]}, "$limit"]}},
        {"$inc": {"used": cost}},
        return_document=ReturnDocument.AFTER,
    )
    return updated is not None


def usage(
    db: Database[dict[str, Any]], settings: Settings, connector_id: str, name: str, now: datetime
) -> dict[str, Any]:
    b = bucket(settings, connector_id, name, now)
    doc = db[COLLECTION].find_one({"_id": b.key})
    return {"limit": b.limit, "used": doc["used"] if doc else 0, "resets_at": b.window_end}
