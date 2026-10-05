"""Whether evidence may support a claim, finding or page now (Step 07.6; D24, D50). One rule for every caller.

Eligibility is computed whenever evidence is used, never stored. Evidence is eligible when:
- the evidence record is active and still holds its words;
- its source revision is active or stale (stale is flagged, not blocked); a temporarily unavailable revision is not
  used meanwhile (Step 05), and deleted, withdrawn, expired and superseded revisions are not eligible;
- the policy it was collected under allowed collection, and the family's current policy allows AI processing;
- its project link is accepted (auto or by a moderator) and belongs to the same project;
- a translation's original is eligible too.
Identity work (alias proposals) may also use evidence whose link is still in review: `for_identity=True`.
`eligible_filter` gives the same rule as a MongoDB filter, so retrieval excludes ineligible evidence before
ranking anything.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from pymongo.client_session import ClientSession
from pymongo.database import Database

from app.identity.links import ACTIVE_STATUSES
from app.sources.policies import ai_processing_allowed

LIFECYCLE_REASON = {
    "withdrawn": "source_withdrawn",
    "deleted": "source_deleted",
    "expired": "policy_expired",
    "superseded": "superseded",
    "unavailable": "source_unavailable",
}
FLAGGED_LIFECYCLES = ("stale",)  # still eligible; shown with the flag
USABLE_SOURCE_LIFECYCLES = ("active", *FLAGGED_LIFECYCLES)
IDENTITY_LINK_STATUSES = (*sorted(ACTIVE_STATUSES), "needs_review")


@dataclass
class Eligibility:
    eligible: bool
    reasons: list[str] = field(default_factory=list)  # why not (contract enum IneligibilityReason)
    flags: list[str] = field(default_factory=list)  # eligible, with care: stale


def eligibility(
    db: Database[dict[str, Any]],
    evidence: dict[str, Any],
    *,
    for_identity: bool = False,
    session: ClientSession | None = None,
    _depth: int = 0,
) -> Eligibility:
    reasons: list[str] = []
    flags: list[str] = []
    source = db["ai_sources"].find_one(
        {"id": evidence["source"]["id"], "revision": evidence["source"]["revision"]},
        {"lifecycle": 1},
        session=session,
    )
    lifecycle = source["lifecycle"] if source else "deleted"
    if lifecycle in LIFECYCLE_REASON:
        reasons.append(LIFECYCLE_REASON[lifecycle])
    elif lifecycle in FLAGGED_LIFECYCLES:
        flags.append(lifecycle)
    if evidence.get("lifecycle") in LIFECYCLE_REASON and LIFECYCLE_REASON[evidence["lifecycle"]] not in reasons:
        reasons.append(LIFECYCLE_REASON[evidence["lifecycle"]])
    if not evidence.get("excerpt_text") and not reasons:
        reasons.append("source_deleted")  # the words were erased
    if not ai_processing_allowed(db, evidence["policy"], session):
        reasons.append("policy_disallows")
    link = db["ai_project_source_links"].find_one(
        {"_id": evidence["link_id"]}, {"status": 1, "project_id": 1}, session=session
    )
    allowed = IDENTITY_LINK_STATUSES if for_identity else ACTIVE_STATUSES
    if link is None or link["status"] not in allowed or link["project_id"] != evidence["project_id"]:
        reasons.append("link_not_accepted")
    original = evidence.get("translation_of")
    if original and _depth == 0:
        parent = db["ai_evidence"].find_one({"id": original["id"], "revision": original["revision"]}, session=session)
        if parent is None:
            reasons.append("source_deleted")
        else:
            inherited = eligibility(db, parent, for_identity=for_identity, session=session, _depth=1)
            reasons += [r for r in inherited.reasons if r not in reasons]
    return Eligibility(not reasons, reasons, flags)


def eligible_filter(
    db: Database[dict[str, Any]], project_id: str, session: ClientSession | None = None
) -> dict[str, Any]:
    """A MongoDB filter on ai_evidence matching exactly the evidence `eligibility` accepts for this project (for
    evidence that is not a translation; translations are re-checked one by one)."""
    links = db["ai_project_source_links"].distinct(
        "_id", {"project_id": project_id, "status": {"$in": sorted(ACTIVE_STATUSES)}}, session=session
    )
    refs = db["ai_project_source_links"].distinct("source", {"_id": {"$in": links}}, session=session)
    usable = {
        f"{s['id']}@{s['revision']}"
        for s in db["ai_sources"].find(
            {
                "_id": {"$in": [f"{r['id']}@{r['revision']}" for r in refs]},
                "lifecycle": {"$in": list(USABLE_SOURCE_LIFECYCLES)},
            },
            {"id": 1, "revision": 1},
            session=session,
        )
    }
    policies = [
        {"family": p["family"], "policy_version": p["policy_version"]}
        for p in db["ai_source_policies"].find({}, {"family": 1, "policy_version": 1}, session=session)
        if ai_processing_allowed(db, {"family": p["family"], "policy_version": p["policy_version"]}, session)
    ]
    return {
        "project_id": project_id,
        "lifecycle": "active",
        "excerpt_text": {"$type": "string"},
        "link_id": {"$in": links},
        "$expr": {"$in": [{"$concat": ["$source.id", "@", {"$toString": "$source.revision"}]}, sorted(usable)]},
        "$or": [{"policy.family": p["family"], "policy.policy_version": p["policy_version"]} for p in policies]
        or [{"_id": {"$exists": False}}],
    }
