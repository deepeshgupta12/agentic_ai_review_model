"""Accepted source policies from seed/source_policies.json (Step 01; versions per D28, D33, D34) until Step 05
moves them into ai_source_policies. Identity work may use a source only when its policy allows AI processing."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any


@lru_cache(maxsize=4)
def _policies(path: str) -> dict[str, dict[str, Any]]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return {p["family"]: p for p in data["policies"] if p["status"] == "accepted"}


def policies(seed_dir: Path) -> dict[str, dict[str, Any]]:
    return _policies(str(seed_dir / "source_policies.json"))


def policy_ref(seed_dir: Path, family: str) -> dict[str, Any]:
    policy = policies(seed_dir).get(family)
    if policy is None:
        raise KeyError(f"no accepted source policy for family {family!r}")
    return {"family": family, "policy_version": policy["policy_version"]}


def ai_processing_allowed(seed_dir: Path, ref: dict[str, Any]) -> bool:
    policy = policies(seed_dir).get(ref["family"])
    return bool(policy and policy["policy_version"] == ref["policy_version"] and policy["ai_processing_allowed"])
