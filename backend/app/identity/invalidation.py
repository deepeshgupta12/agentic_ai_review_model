"""invalidate_dependencies jobs for source links (Step 04.6, docs/02 invariants, docs/05).

When a link leaves an accepted state (a moderator rejects, splits or remaps it, or a revoked alias sends it
back to review), the evidence on it stops being eligible at once, because eligibility is computed from the
link status whenever evidence is read. This job records what depended on the link. Claims, findings, source
reviews and content revisions are added to DEPENDANTS as Steps 07-11 build them, so the same job sends them
back to review and withdraws affected approvals.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from pymongo.database import Database

from app import audit

# Collections whose records cite evidence, in the order later steps add them. Empty until they exist.
DEPENDANTS: list[str] = []


def target_of(logical_key: str) -> str:
    """invalidate_dependencies:link:<link id>:v<version> -> link id."""
    parts = logical_key.split(":")
    if len(parts) != 4 or parts[0] != "invalidate_dependencies" or parts[1] != "link":
        raise ValueError(f"unsupported invalidation key {logical_key!r}")
    return parts[2]


def handle(db: Database[dict[str, Any]], job: dict[str, Any], check: Callable[[], str]) -> str | None:
    link_id = target_of(job["logical_key"])
    check()
    link = db["ai_project_source_links"].find_one({"_id": link_id})
    evidence = db["ai_evidence"].count_documents({"link_id": link_id})
    details: dict[str, Any] = {
        "link_status": link["status"] if link else "missing",
        "evidence_made_ineligible": evidence if link and link["status"] not in ("auto_accepted", "accepted") else 0,
    }
    for name in DEPENDANTS:
        details[name] = 0
    audit.record(db, "dependencies.invalidated", "project_source_link", link_id, audit.SYSTEM_ACTOR, details=details)
    return None
