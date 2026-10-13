"""Construction-status consistency (D27; contracts/v1/content_rules.json). Backend code, never a model.

A claim or review written from first-hand living experience (`resident_experience`) is only possible once the
project, or its phase, is ready. The status in force on the observation date decides:
- records for the claim's own phase (by RERA ID) come before project-wide ones;
- the latest record dated on or before the observation date applies; with no date, the latest record;
- before the first record: if that first record already says occupancy was not possible, it was not possible
  earlier either (projects do not move backwards); otherwise the status is unknown.
Flags: `occupancy_before_possession` when occupancy was not possible, `status_unknown` when it cannot be told
(including a partly ready project with no phase identified). D63 adds two checks for when occupancy was possible on
the claim's date: `awaiting_after_handover` (written as an owner still waiting for possession) and
`construction_after_completion` (a complaint about construction progress). A flagged claim or review stays out of
findings and content until a moderator resolves it.
"""

from __future__ import annotations

import json
from datetime import date, datetime
from functools import lru_cache
from typing import Any

from app.config import REPO_ROOT


@lru_cache(maxsize=1)
def rules() -> dict[str, Any]:
    data: dict[str, Any] = json.loads((REPO_ROOT / "contracts" / "v1" / "content_rules.json").read_text("utf-8"))
    return data


def _day(value: Any) -> date | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def status_in_force(records: list[dict[str, Any]], rera_id: str | None, on: date | None) -> str | None:
    def pick(candidates: list[dict[str, Any]]) -> str | None:
        dated = sorted((r for r in candidates if _day(r.get("as_of"))), key=lambda r: _day(r["as_of"]))  # type: ignore[arg-type,return-value]
        if not dated:
            return None
        if on is None:
            return str(dated[-1]["status"])
        before = [r for r in dated if _day(r["as_of"]) <= on]  # type: ignore[operator]
        if before:
            return str(before[-1]["status"])
        first = str(dated[0]["status"])
        return first if rules()["occupancy_possible"].get(first) == "no" else None

    phase = [r for r in records if (r.get("applies_to") or {}).get("rera_id") == rera_id] if rera_id else []
    project = [r for r in records if (r.get("applies_to") or {}).get("kind") == "project"]
    return pick(phase) or pick(project)


def consistency_flags(
    perspective: str,
    records: list[dict[str, Any]],
    rera_id: str | None,
    on: Any,
    aspects: list[str] | tuple[str, ...] = (),
    polarity: str | None = None,
) -> list[str]:
    observed = _day(on)
    phase_status = (
        status_in_force([r for r in records if (r.get("applies_to") or {}).get("rera_id")], rera_id, observed)
        if rera_id
        else None
    )
    status = phase_status or status_in_force(records, None, observed)
    possible = rules()["occupancy_possible"].get(status) if status else None
    flags: list[str] = []
    if perspective in rules()["occupancy_perspectives"]:
        if possible == "no":
            flags.append("occupancy_before_possession")
        elif possible != "yes":
            flags.append("status_unknown")  # unknown, or a partly ready project with no phase identified
    if possible == "yes":  # D63: checks that apply once occupancy was possible on the claim's date
        checks = rules()["status_checks"]
        if perspective in checks["awaiting_after_handover"]["perspectives"]:
            flags.append("awaiting_after_handover")
        construction = checks["construction_after_completion"]
        if polarity in construction["polarities"] and set(aspects) & set(construction["aspects"]):
            flags.append("construction_after_completion")
    return flags
