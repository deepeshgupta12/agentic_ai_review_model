"""What every specialist agent shares (Step 08.2; docs/04 shared execution envelope).

- Handles: a model never sees database IDs. Each task gives its inputs short handles (e1, e2, c1, ...) and maps
  them back; a handle the task did not give is an invented reference and is rejected, however valid the JSON.
- Stable IDs: records made from a task's output get IDs derived from the task key and the item, so a node that runs
  again after a crash writes the same records, never duplicates.
- Task cache: a task's validated model output is kept under its key (`ai_agent_outputs`). A restarted node reuses
  it instead of paying for the call again.
- Run records: every task, cached or not, leaves an ai_agent_runs record with its exact inputs and outputs.
"""

from __future__ import annotations

import hashlib
import re
import time
import unicodedata
from dataclasses import dataclass, field
from typing import Any

from pymongo.database import Database

from app.agents.gateway import GatewayResult
from app.db import utcnow
from app.ids import new_id

OUTPUTS = "ai_agent_outputs"
CROCKFORD = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
NUMBER = re.compile(r"\d[\d,]*(?:\.\d+)?")


def numbers_in(text: str | None) -> set[str]:
    """The numbers a text states, without thousands separators and in ASCII digits (Devanagari digits fold), so a
    model's wording may only repeat these."""
    found = set()
    for m in NUMBER.finditer(text or ""):
        found.add("".join(str(unicodedata.decimal(ch)) if ch.isdigit() else ch for ch in m.group(0)))
    return {n.replace(",", "").rstrip(".") for n in found}


def stable_id(prefix: str, *parts: str) -> str:
    """A prefixed, ULID-shaped ID that is the same for the same parts (26 Crockford base-32 characters)."""
    digest = int.from_bytes(hashlib.sha256("\x1f".join(parts).encode("utf-8")).digest()[:17], "big")
    chars = []
    for _ in range(26):
        digest, rest = divmod(digest, 32)
        chars.append(CROCKFORD[rest])
    body = "".join(reversed(chars))
    return f"{prefix}_{'0' + body[1:] if body[0] not in '01234567' else body}"  # a ULID starts at most at 7


@dataclass
class Handles:
    """Short handles for one task's inputs: `prefix` + position, mapped to whatever the task needs back."""

    prefix: str
    items: dict[str, Any] = field(default_factory=dict)

    def add(self, value: Any) -> str:
        handle = f"{self.prefix}{len(self.items) + 1}"
        self.items[handle] = value
        return handle

    def resolve(self, handles: list[str]) -> tuple[list[Any], list[str]]:
        """(the known items, the unknown handles). Unknown handles are invented references."""
        known: list[Any] = []
        invented: list[str] = []
        for h in dict.fromkeys(handles):
            (known if h in self.items else invented).append(self.items.get(h, h))
        return known, invented


def version_digest(prompt_path: Any, role: str) -> str:
    """What a cached task output depends on besides its inputs: the prompt's exact text and the model behind the role
    (a prompt edited without a new version, or another model, never reuses old outputs; audit, 14 Oct 2026)."""
    from app.config import get_settings

    model = get_settings().model_for_role(role)
    return hashlib.sha256(f"{model}|{prompt_path.read_text('utf-8')}".encode()).hexdigest()[:16]


def mark_split(db: Database[dict[str, Any]], key: str) -> None:
    """A task whose answer was cut off was split: a later pass goes straight to its halves, never paying again for
    the whole (audit, 14 Oct 2026)."""
    keep_output(db, f"{key}:split", "split", {"split": True})


def failed_before(db: Database[dict[str, Any]], key: str, code: str) -> bool:
    """Whether this task already failed with this code in an earlier pass; records it now. A task failing the same way
    twice is skipped and reported, so one bad task cannot block every Continue (audit, 14 Oct 2026)."""
    marker = f"{key}:failed:{code}"
    seen = db[OUTPUTS].find_one({"_id": marker}, {"_id": 1}) is not None
    if not seen:
        keep_output(db, marker, "failed", {"code": code})
    return seen


def was_split(db: Database[dict[str, Any]], key: str) -> bool:
    return db[OUTPUTS].find_one({"_id": f"{key}:split"}, {"_id": 1}) is not None


def cached_output(db: Database[dict[str, Any]], key: str) -> dict[str, Any] | None:
    doc = db[OUTPUTS].find_one({"_id": key})
    return doc["data"] if doc else None


def keep_output(db: Database[dict[str, Any]], key: str, agent: str, data: dict[str, Any]) -> None:
    db[OUTPUTS].update_one(
        {"_id": key}, {"$setOnInsert": {"agent": agent, "data": data, "created_at": utcnow()}}, upsert=True
    )


def record_run(
    db: Database[dict[str, Any]],
    *,
    agent: str,
    task_key: str,
    run_id: str | None,
    project_id: str,
    prompt_version: str,
    schema_version: str,
    result: GatewayResult | None,
    input_refs: list[dict[str, Any]],
    output_refs: list[dict[str, Any]],
    outcome: str,
    started: float,
) -> str:
    """One ai_agent_runs record per task and run (AgentRun contract); a restarted node replaces its own record but
    keeps what earlier attempts cost: each paid attempt adds to it, and a reused cached output (`result` None, no
    model call) adds nothing (audit, 14 Oct 2026: a cache hit used to erase the recorded cost)."""
    task_id = stable_id("tsk", task_key, run_id or "")
    prior = db["ai_agent_runs"].find_one({"_id": task_id}, {"estimated_cost_usd": 1}) or {}
    spent = float(prior.get("estimated_cost_usd") or 0.0) + float(
        result.cost_usd if result and result.cost_usd else 0.0
    )
    db["ai_agent_runs"].replace_one(
        {"_id": task_id},
        {
            "_id": task_id,
            "run_id": run_id or new_id("run"),
            "project_id": project_id,
            "agent": agent,
            "outcome": outcome,
            "input_refs": input_refs[:200],
            "output_refs": output_refs[:200],
            "prompt_version": prompt_version,
            "schema_version": schema_version,
            "requested_model": result.requested_model if result else None,
            "returned_model": result.returned_model if result else None,
            "stop_reason": result.stop_reason if result else None,
            "tool_steps": 0,
            "attempt": max(1, result.attempts) if result else 1,
            "repair_used": result.repair_used if result else False,
            "usage": result.usage
            if result
            else {"input_tokens": None, "output_tokens": None, "cache_read_input_tokens": None, "audio_seconds": None},
            "estimated_cost_usd": round(spent, 6) if spent else None,
            "provider_request_id": result.provider_request_id if result else None,
            "elapsed_ms": int((time.monotonic() - started) * 1000),
            "error": {"code": result.error["code"], "message": result.error["message"][:300]}
            if result and result.error
            else None,
            "created_at": utcnow(),
        },
        upsert=True,
    )
    return task_id
