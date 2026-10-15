"""Model spend: cost estimates and a hard budget for live Claude calls (Step 08.1; D53).

Every live call is priced from its reported usage with the price table in configuration (USD per million tokens,
from Anthropic's published prices; the Batch API halves input and output). Before a call, the gateway reserves its
worst case (all input uncached, the cached prefix at the cache-write price, every allowed output token) against one
budget record; the reservation is a single
conditional update, so concurrent workers cannot overspend together. After the call the reservation is released and
the actual cost added. A call that would not fit is refused with `budget_exhausted`. Each call leaves a ledger entry.
A model without a price cannot be called: its cost could not be bounded.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from pymongo import ReturnDocument
from pymongo.database import Database

from app.config import Settings
from app.db import utcnow
from app.ids import new_id

BUDGETS = "ai_model_budget"
CALLS = "ai_model_calls"
# Each open hold on the budget, so a hold left by a worker killed mid-call is released later (audit, 14 Oct 2026).
HOLDS = "ai_model_holds"
HOLD_MINUTES = 60  # longer than any call with its retries; an older hold was left behind
IMAGE_TOKENS = 1600  # a frame scaled to 768 px is at most about 1,600 input tokens
CHARS_PER_TOKEN = 2.0  # conservative for Hindi and JSON; real counts come back in usage


class PriceUnknown(Exception):
    pass


@dataclass
class Reservation:
    budget_id: str
    amount_usd: float
    model: str
    batch: bool
    hold_id: str | None = None


def price_of(settings: Settings, model: str) -> dict[str, float]:
    prices = settings.model_prices.get(model)
    if prices is None:
        raise PriceUnknown(f"no price configured for {model}; its cost cannot be bounded")
    return prices


def estimate_input_tokens(system: str, content: str | list[dict[str, Any]]) -> int:
    if isinstance(content, str):
        chars, images = len(system) + len(content), 0
    else:
        texts = [b.get("text", "") for b in content if b.get("type") == "text"]
        images = sum(1 for b in content if b.get("type") == "image")
        chars = len(system) + sum(len(t) for t in texts)
    return int(chars / CHARS_PER_TOKEN) + images * IMAGE_TOKENS + 50


def cache_write_price(p: dict[str, float], ttl: str) -> float:
    """USD per million tokens written to the cache: 1.25 times input for 5 minutes, twice input for 1 hour (D65)."""
    return p["cache_write"] if ttl == "5m" else 2 * p["input"]


def worst_case_usd(
    settings: Settings,
    model: str,
    input_tokens: int,
    max_tokens: int,
    *,
    batch: bool,
    cached_tokens: int = 0,
    ttl: str = "5m",
) -> float:
    """`cached_tokens` of the input sit before a cache breakpoint and may be written to the cache (D65)."""
    p = price_of(settings, model)
    cached = min(cached_tokens, input_tokens)
    cost = (
        (input_tokens - cached) * p["input"] + cached * cache_write_price(p, ttl) + max_tokens * p["output"]
    ) / 1_000_000
    return round(cost * (0.5 if batch else 1.0), 6)


def actual_usd(settings: Settings, model: str, usage: dict[str, Any], *, batch: bool) -> float:
    """Usage as reported: tokens after the last breakpoint, cache writes (5-minute and 1-hour), cache reads, output."""
    p = price_of(settings, model)
    written = usage.get("cache_creation_input_tokens") or 0
    written_1h = min(written, usage.get("cache_creation_1h_input_tokens") or 0)
    cost = (
        (usage.get("input_tokens") or 0) * p["input"]
        + (written - written_1h) * cache_write_price(p, "5m")
        + written_1h * cache_write_price(p, "1h")
        + (usage.get("cache_read_input_tokens") or 0) * p["cache_read"]
        + (usage.get("output_tokens") or 0) * p["output"]
    ) / 1_000_000
    return round(cost * (0.5 if batch else 1.0), 6)


class SpendLedger:
    """The budget for live calls since `model_budget_since`, held in one record per budget period."""

    def __init__(self, db: Database[dict[str, Any]], settings: Settings) -> None:
        self.db, self.settings = db, settings
        self.budget_id = f"since:{settings.model_budget_since.isoformat()}"

    def _ensure(self) -> None:
        self.db[BUDGETS].update_one(
            {"_id": self.budget_id},
            {
                "$setOnInsert": {"spent_usd": 0.0, "reserved_usd": 0.0, "calls": 0, "created_at": utcnow()},
                "$set": {"limit_usd": float(self.settings.model_budget_usd)},
            },
            upsert=True,
        )

    def state(self) -> dict[str, Any]:
        self._ensure()
        doc = self.db[BUDGETS].find_one({"_id": self.budget_id}) or {}
        left = doc["limit_usd"] - doc["spent_usd"] - doc["reserved_usd"]
        return {
            "budget": self.budget_id,
            "limit_usd": doc["limit_usd"],
            "spent_usd": round(doc["spent_usd"], 6),
            "reserved_usd": round(doc["reserved_usd"], 6),
            "left_usd": round(left, 6),
            "calls": doc["calls"],
        }

    def reserve(self, model: str, amount_usd: float, *, batch: bool) -> Reservation | None:
        """Hold `amount_usd` if it fits under the limit; None when it does not."""
        self._ensure()
        held = self.db[BUDGETS].find_one_and_update(
            {
                "_id": self.budget_id,
                "$expr": {"$lte": [{"$add": ["$spent_usd", "$reserved_usd", amount_usd]}, "$limit_usd"]},
            },
            {"$inc": {"reserved_usd": amount_usd}, "$set": {"updated_at": utcnow()}},
            return_document=ReturnDocument.AFTER,
        )
        if not held:
            return None
        hold_id = new_id("hld")
        self.db[HOLDS].insert_one(
            {"_id": hold_id, "budget": self.budget_id, "amount_usd": amount_usd, "model": model, "at": utcnow()}
        )
        return Reservation(self.budget_id, amount_usd, model, batch, hold_id)

    def settle(
        self,
        reservation: Reservation,
        usage: dict[str, Any] | None,
        *,
        purpose: str,
        outcome: str,
        error_code: str | None = None,
        request_id: str | None = None,
    ) -> float:
        """Release the hold, add the actual cost (zero when nothing was billed) and write the ledger entry."""
        cost = actual_usd(self.settings, reservation.model, usage or {}, batch=reservation.batch) if usage else 0.0
        if reservation.hold_id is not None:
            released = self.db[HOLDS].delete_one({"_id": reservation.hold_id}).deleted_count
            if not released:  # the hold was released as stale already: only the cost is added now
                reservation = Reservation(reservation.budget_id, 0.0, reservation.model, reservation.batch)
        self.db[BUDGETS].update_one(
            {"_id": reservation.budget_id},
            {
                "$inc": {"reserved_usd": -reservation.amount_usd, "spent_usd": cost, "calls": 1},
                "$set": {"updated_at": utcnow()},
            },
        )
        self.db[CALLS].insert_one(
            {
                "_id": new_id("mcl"),
                "budget": reservation.budget_id,
                "at": utcnow(),
                "model": reservation.model,
                "purpose": purpose,
                "batch": reservation.batch,
                "usage": json.loads(json.dumps(usage or {}, default=str)),
                "estimate_usd": reservation.amount_usd,
                "cost_usd": cost,
                "outcome": outcome,
                "error_code": error_code,
                "provider_request_id": request_id,
            }
        )
        return cost


def since(settings: Settings) -> datetime:
    return settings.model_budget_since


def release_stale_holds(db: Database[dict[str, Any]], older_than_minutes: int = HOLD_MINUTES) -> int:
    """Holds older than any call can take were left by a worker that stopped mid-call: their amount goes back to the
    budget (the scheduler runs this), so the budget never shrinks for nothing."""
    from datetime import timedelta

    released = 0
    for hold in db[HOLDS].find({"at": {"$lt": utcnow() - timedelta(minutes=older_than_minutes)}}):
        if db[HOLDS].delete_one({"_id": hold["_id"]}).deleted_count:
            db[BUDGETS].update_one({"_id": hold["budget"]}, {"$inc": {"reserved_usd": -hold["amount_usd"]}})
            released += 1
    return released
