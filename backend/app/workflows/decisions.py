"""Moderator decisions on findings and first-person reviews (Step 08.6; docs/05; state machines `finding_review` and
`review_excerpt`; D27, D28).

A decision names the exact revision it is about; a newer revision makes it a version conflict. The actor comes from
the session and is always a person: models cannot approve. Before an approval the backend re-checks, whatever the
console showed:
- a finding: every claim revision it cites belongs to the project and has no consistency flag; the attribution still
  follows from the claims (verified_fact only when every claim is verified; one origin keeps reported_opinion);
  every supporting evidence span is still eligible;
- a review: no consistency flag; the shown words still match the original unless translated; every span still
  eligible and its family's current policy still allows quotation.
Each decision is one transaction: the append-only decision record, the status change at the expected status, and
an audit event.
"""

from __future__ import annotations

from typing import Any

from pymongo import MongoClient
from pymongo.client_session import ClientSession
from pymongo.database import Database

from app import audit
from app.agents.findings import attribution_for
from app.agents.reviews import rendering_problem
from app.contracts import ContractStore, to_view
from app.db import run_in_transaction
from app.decisions import record_decision
from app.errors import ApiError
from app.evidence.clusters import independent_origins
from app.evidence.eligibility import eligibility
from app.sources import policies

STATUS_FOR = {"approve": "approved", "reject": "rejected", "changes_requested": "changes_requested"}


def _latest(db: Database[dict[str, Any]], collection: str, record_id: str, session: ClientSession | None) -> Any:
    return db[collection].find_one({"id": record_id}, sort=[("revision", -1)], session=session)


def evidence_for(
    db: Database[dict[str, Any]], refs: list[dict[str, Any]], session: ClientSession | None = None
) -> list[dict[str, Any]]:
    keys = sorted({f"{r['id']}@{r['revision']}" for r in refs})
    found = {
        f"{e['id']}@{e['revision']}": e
        for e in db["ai_evidence"].find({"id": {"$in": sorted({r["id"] for r in refs})}}, session=session)
    }
    return [found[k] for k in keys if k in found]


def finding_problems(
    db: Database[dict[str, Any]], finding: dict[str, Any], session: ClientSession | None = None
) -> list[str]:
    """Why this finding revision may not be approved now (empty when it may)."""
    problems: list[str] = []
    claims = [
        db["ai_claims"].find_one({"id": c["id"], "revision": c["revision"]}, session=session) for c in finding["claims"]
    ]
    if any(c is None for c in claims):
        return ["a cited claim revision is missing"]
    present = [c for c in claims if c is not None]
    if any(c["project_id"] != finding["project_id"] for c in present):
        problems.append("a cited claim belongs to another project")
    if any(c["consistency_flags"] for c in present):
        problems.append("a cited claim has a construction-status flag (D27)")
    support = [e for c in present for e in c["supporting_evidence"]]
    if finding["attribution"] != attribution_for(present, len(independent_origins(db, support))):
        problems.append("the attribution no longer follows from the claims")
    spans = evidence_for(db, support, session)
    wanted = {f"{e['id']}@{e['revision']}" for e in support}
    if len(spans) < len(wanted) or any(not eligibility(db, e, session=session).eligible for e in spans):
        problems.append("supporting evidence is no longer eligible")
    return problems


def review_problems(
    db: Database[dict[str, Any]], review: dict[str, Any], session: ClientSession | None = None
) -> list[str]:
    """Why this review revision may not be approved now (empty when it may)."""
    problems: list[str] = []
    if review["consistency_flags"]:
        problems.append("the review has a construction-status flag (D27)")
    if review["lifecycle"] != "active" or review["text"] is None or review["original_text"] is None:
        return [*problems, "the review's words were erased"]
    spans = evidence_for(db, review["evidence"], session)
    if len(spans) < len(review["evidence"]) or any(not eligibility(db, e, session=session).eligible for e in spans):
        problems.append("a span is no longer eligible")
    if review["rendering"] != "translated" and rendering_problem(
        review["rendering"], review["text"], review["original_text"], [review["original_language"]], ""
    ):
        problems.append("the shown words no longer match the original")
    policy = policies.current(db, review["policy"]["family"], session=session)
    if policy is None or not policy["quotation_allowed"]:
        problems.append("the source policy no longer allows quotation")
    return problems


def _decide(
    client: MongoClient[dict[str, Any]],
    db: Database[dict[str, Any]],
    contracts: ContractStore,
    *,
    collection: str,
    machine: str,
    target_type: str,
    record_id: str,
    body: dict[str, Any],
    actor: dict[str, Any],
) -> dict[str, Any]:
    to = STATUS_FOR[body["action"]]

    def write(session: ClientSession) -> str:
        latest = _latest(db, collection, record_id, session)
        if latest is None:
            raise ApiError(404, "not_found", f"No such {target_type.replace('_', ' ')}")
        if latest["revision"] != body["revision"]:
            raise ApiError(
                409,
                "version_conflict",
                f"Revision {body['revision']} is not the latest; revision {latest['revision']} is",
                current_version=latest["revision"],
            )
        current = latest["review_status"]
        if not contracts.transition_allowed(machine, current, to, actor["role"]):
            raise ApiError(409, "invalid_transition", f"A {actor['role']} cannot move a {current} revision to {to}")
        if to == "approved":
            problems = (
                finding_problems(db, latest, session)
                if target_type == "finding"
                else review_problems(db, latest, session)
            )
            if problems:
                raise ApiError(409, "ineligible_dependency", "Cannot approve: " + "; ".join(problems))
        decision_id = record_decision(
            db,
            target_type=target_type,
            target_id=record_id,
            revision=latest["revision"],
            action=body["action"],
            reason=body["reason"],
            actor=actor,
            session=session,
        )
        changed = db[collection].update_one(
            {"_id": latest["_id"], "review_status": current}, {"$set": {"review_status": to}}, session=session
        )
        if changed.modified_count != 1:
            raise ApiError(
                409, "version_conflict", "The revision changed; reload it", current_version=latest["revision"]
            )
        audit.record(
            db,
            f"{'finding' if target_type == 'finding' else 'review'}.decided",
            target_type,
            record_id,
            actor,
            revision=latest["revision"],
            details={"action": body["action"], "from": current, "to": to},
            session=session,
        )
        return decision_id

    decision_id = run_in_transaction(client, write)
    view = to_view(db["ai_review_decisions"].find_one({"_id": decision_id}))
    assert view is not None
    return view


def decide_finding(
    client: MongoClient[dict[str, Any]],
    db: Database[dict[str, Any]],
    contracts: ContractStore,
    finding_id: str,
    body: dict[str, Any],
    actor: dict[str, Any],
) -> dict[str, Any]:
    return _decide(
        client,
        db,
        contracts,
        collection="ai_findings",
        machine="finding_review",
        target_type="finding",
        record_id=finding_id,
        body=body,
        actor=actor,
    )


def decide_review(
    client: MongoClient[dict[str, Any]],
    db: Database[dict[str, Any]],
    contracts: ContractStore,
    excerpt_id: str,
    body: dict[str, Any],
    actor: dict[str, Any],
) -> dict[str, Any]:
    return _decide(
        client,
        db,
        contracts,
        collection="ai_review_excerpts",
        machine="review_excerpt",
        target_type="review_excerpt",
        record_id=excerpt_id,
        body=body,
        actor=actor,
    )
