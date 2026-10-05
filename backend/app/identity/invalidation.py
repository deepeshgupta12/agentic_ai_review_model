"""invalidate_dependencies jobs (Step 04.6, Step 07.5-07.6; docs/02 invariants, docs/05; D50).

A link leaves an accepted state (a moderator rejects, splits or remaps it, or a revoked alias sends it back to
review), or its source revision is withdrawn, deleted, expired or superseded by an edit, or a policy version takes
rights away. The evidence involved stops being eligible at once, because eligibility is computed whenever evidence
is used (app.evidence.eligibility). This job then follows the lineage (app.evidence.lineage) to everything that
cites that evidence:
- content revisions in final review or approved are withdrawn (content_lifecycle: system), so an approval can never
  outlive its evidence; drafts and revisions with requested changes are reported, and fail eligibility at approval;
- claims, findings and source reviews are reported by exact revision for re-review in the console.
Erasure of the source text waits until these jobs have finished (app.sources.lifecycle.handle_erase).
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from pymongo.client_session import ClientSession
from pymongo.database import Database

from app import audit
from app.contracts import get_contracts
from app.db import run_in_transaction
from app.evidence.eligibility import eligibility
from app.evidence.lineage import affected, counts

WITHDRAWABLE = ("final_review", "approved")
LISTED = 50  # exact references kept in the audit event; counts are always complete


def target_of(logical_key: str) -> tuple[str, str]:
    """invalidate_dependencies:<link|policy>:<id or family>:v<version> -> (kind, id or family)."""
    parts = logical_key.split(":")
    if len(parts) != 4 or parts[0] != "invalidate_dependencies" or parts[1] not in ("link", "policy"):
        raise ValueError(f"unsupported invalidation key {logical_key!r}")
    return parts[1], parts[2]


def handle(db: Database[dict[str, Any]], job: dict[str, Any], check: Callable[[], str]) -> str | None:
    kind, target = target_of(job["logical_key"])
    check()
    if kind == "policy":
        details: dict[str, Any] = {
            "family": target,
            "sources": db["ai_sources"].count_documents({"policy.family": target}),
        }
        evidence = list(db["ai_evidence"].find({"policy.family": target}))
        _act(db, "source_policy", target, evidence, details, reason=f"policy family {target} narrowed")
        return None
    link = db["ai_project_source_links"].find_one({"_id": target})
    evidence = list(db["ai_evidence"].find({"link_id": target}))
    details = {"link_status": link["status"] if link else "missing"}
    _act(db, "project_source_link", target, evidence, details, reason=f"link {target} or its source changed")
    return None


def _act(
    db: Database[dict[str, Any]],
    target_type: str,
    target_id: str,
    evidence: list[dict[str, Any]],
    details: dict[str, Any],
    *,
    reason: str,
) -> None:
    """Withdraw approvals that rest on evidence that is no longer eligible, and record the whole lineage."""
    ineligible = [e for e in evidence if not eligibility(db, e).eligible]
    lineage = affected(db, evidence=[{"id": e["id"], "revision": e["revision"]} for e in ineligible])
    contracts = get_contracts()
    # Audit details hold flat values only (AuditEvent contract): counts, plus exact references joined as text.
    summary = {
        **details,
        "evidence_made_ineligible": len(ineligible),
        **counts(lineage),
        "claim_refs": _joined(f"{r['id']}@{r['revision']}" for r in lineage["claims"]),
        "finding_refs": _joined(f"{r['id']}@{r['revision']}" for r in lineage["findings"]),
        "review_refs": _joined(f"{r['id']}@{r['revision']}" for r in lineage["reviews"]),
        "content_refs": _joined(f"{c['id']} ({c['lifecycle']})" for c in lineage["content_revisions"]),
    }

    def write(session: ClientSession) -> None:
        withdrawn = []
        for content in lineage["content_revisions"]:
            current = content["lifecycle"]
            if current not in WITHDRAWABLE or not contracts.transition_allowed(
                "content_lifecycle", current, "withdrawn", "system"
            ):
                continue
            result = db["ai_content_revisions"].update_one(
                {"_id": content["id"], "lifecycle": current}, {"$set": {"lifecycle": "withdrawn"}}, session=session
            )
            if result.modified_count:
                withdrawn.append(content["id"])
                audit.record(
                    db,
                    "content_revision.withdrawn",
                    "content_revision",
                    content["id"],
                    audit.SYSTEM_ACTOR,
                    revision=content["revision"],
                    details={"from": current, "reason": reason},
                    session=session,
                )
        audit.record(
            db,
            "dependencies.invalidated",
            target_type,
            target_id,
            audit.SYSTEM_ACTOR,
            details={**summary, "content_withdrawn": _joined(withdrawn)},
            session=session,
        )

    run_in_transaction(db.client, write)


def _joined(items: Any) -> str | None:
    listed = list(items)
    if not listed:
        return None
    more = len(listed) - LISTED
    return ", ".join(listed[:LISTED]) + (f" and {more} more" if more > 0 else "")
