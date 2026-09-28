"""Bounded search queries per project (Step 04.3). Deterministic and versioned (QUERY_RULES_VERSION).

Uses the project name, approved aliases (never unapproved proposals, D17), phase names and identifiers
(RERA IDs; developer with sector) so unknown names can surface. A context-required alias is always paired
with the developer or locality. Exclusions are the configured negative keywords and rejected proposals.
Queries are deduplicated and capped per connector. The result has the DiscoveryPlan shape (A02 output)
so collectors and A02 read the same thing.
"""

from __future__ import annotations

from typing import Any

from pymongo.database import Database

from app.identity.catalogue import ProjectIdentity, identity_from_records
from app.identity.rules import ALIAS_ORIGIN_ORDER, MAX_QUERIES_PER_CONNECTOR, QUERY_PRIORITY, QUERY_RULES_VERSION
from app.identity.text import normalise_text

PRIORITY_ORDER = {"high": 0, "normal": 1, "low": 2}


def _script_language(text: str) -> str:
    return "hi" if any("ऀ" <= ch <= "ॿ" for ch in text) else "en"


def query_texts(identity: ProjectIdentity, project: dict[str, Any]) -> list[tuple[str, str]]:
    """(purpose, query text) pairs before connector fan-out, in priority order."""
    city = project["city"]
    locality = project["locality"]
    developer = project.get("developer")
    pairs: list[tuple[str, str, int]] = [
        ("project_name", f"{identity.name} {city}", 0),
        ("project_name", f"{identity.name} {locality}", 0),
        ("project_name", f"{identity.name} review", 0),
    ]
    for phase in identity.phases:
        pairs.append(("identifier", phase.rera_id, 0))
    if developer:
        pairs.append(("identifier", f"{developer} {locality} {city}", 0))
    for alias in identity.aliases:
        if alias.normalised == identity.name_norm:
            continue
        purpose = "phase_name" if alias.target_kind == "phase" else "approved_alias"
        rank = ALIAS_ORIGIN_ORDER.get(alias.origin, 9)
        if alias.mode == "standalone":
            pairs.append((purpose, f"{alias.text} {city}", rank))
        else:
            context = developer if developer and normalise_text(developer) not in alias.normalised else locality
            pairs.append((purpose, f"{alias.text} {context}", rank))
    ordered = sorted(pairs, key=lambda p: (PRIORITY_ORDER[QUERY_PRIORITY[p[0]]], p[2]))
    return [(purpose, text) for purpose, text, _ in ordered]


def build_query_plan(
    db: Database[dict[str, Any]], project_id: str, connectors: dict[str, dict[str, Any]]
) -> dict[str, Any]:
    """{"project_id", "rules_version", "plan": DiscoveryPlan} for one project's enabled, search-capable connectors."""
    project = db["projects"].find_one({"_id": project_id})
    config = db["ai_project_configs"].find_one({"_id": project_id})
    if project is None or config is None:
        raise KeyError(project_id)
    identity = identity_from_records(project, config)
    rejected = [
        p["alias_text"]
        for p in db["ai_alias_proposals"].find({"project_id": project_id, "status": {"$in": ["rejected", "revoked"]}})
    ]
    exclusions = list(dict.fromkeys([*config["negative_keywords"], *rejected]))
    enabled = [
        s["connector_id"]
        for s in config["sources"]
        if s["enabled"] and connectors.get(s["connector_id"], {}).get("expected_capabilities", {}).get("search") is True
    ]
    pairs = query_texts(identity, project)
    queries: list[dict[str, Any]] = []
    for connector_id in enabled:
        seen: set[str] = set()
        for purpose, text in pairs:
            key = normalise_text(text)
            if not key or key in seen:
                continue
            seen.add(key)
            queries.append(
                {
                    "connector_id": connector_id,
                    "query_text": " ".join(text.split()),
                    "window_days": config["refresh"]["lookback_days"],
                    "language": _script_language(text),
                    "exclusions": exclusions,
                    "priority": QUERY_PRIORITY[purpose],
                    "purpose": purpose,
                }
            )
            if len(seen) >= MAX_QUERIES_PER_CONNECTOR:
                break
    return {
        "project_id": project_id,
        "rules_version": QUERY_RULES_VERSION,
        "plan": {"outcome": "completed", "queries": queries},
    }
