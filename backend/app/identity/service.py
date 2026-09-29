"""Identify one stored source revision against the catalogue (Step 04.4, 04.5).

Deterministic matching first; links and their evidence spans are written in one transaction; then, when an
API key is configured, A01 looks at the segments that went to review, one bounded task per project.
Collectors (Step 05) call identify_source after storing each source revision.
"""

from __future__ import annotations

from typing import Any

from pymongo import MongoClient
from pymongo.client_session import ClientSession
from pymongo.database import Database

from app import audit
from app.agents.gateway import ModelGateway
from app.contracts import ContractStore
from app.db import run_in_transaction
from app.identity.agent import run_identity_agent
from app.identity.catalogue import load_identities
from app.identity.evidence import create_link_evidence
from app.identity.intake import source_text
from app.identity.links import ACTIVE_STATUSES, insert_outcomes, new_link
from app.identity.matching import Segment, match_text
from app.ids import new_id


def identify_source(
    client: MongoClient[dict[str, Any]],
    db: Database[dict[str, Any]],
    contracts: ContractStore,
    source: dict[str, Any],
    *,
    focus_project_ids: list[str] | None = None,
    gateway: ModelGateway | None = None,
    run_id: str | None = None,
) -> dict[str, Any]:
    text = source_text(db, source)
    report: dict[str, Any] = {"source": {"id": source["id"], "revision": source["revision"]}, "links": [], "a01": []}
    if text is None:
        report["note"] = "no stored text: metadata-only or erased sources are not matched"
        return report
    identities = load_identities(db)
    outcomes = match_text(identities, text, focus_project_ids)

    def write(session: ClientSession) -> list[tuple[dict[str, Any], dict[str, Any] | None, bool]]:
        rows = []
        for link, created in insert_outcomes(db, source, outcomes, session):
            evidence = create_link_evidence(db, link, source, text, session) if link["status"] != "rejected" else None
            if created:
                audit.record(
                    db,
                    "source_link.created",
                    "project_source_link",
                    link["_id"],
                    audit.SYSTEM_ACTOR,
                    details={"status": link["status"], "segment": link["segment_key"]},
                    session=session,
                )
            rows.append((link, evidence, created))
        return rows

    rows = run_in_transaction(client, write)
    report["links"] = [
        {
            "link_id": link["_id"],
            "project_id": link["project_id"],
            "segment_key": link["segment_key"],
            "status": link["status"],
            "matched_alias": link["match"]["matched_alias"],
            "phase": link["phase"],
            "created": created,
        }
        for link, _, created in rows
    ]
    if gateway is None or not gateway.available:
        return report
    run_id = run_id or new_id("run")
    groups: dict[str, list[dict[str, Any]]] = {}
    for link, evidence, created in rows:
        if created and link["status"] == "needs_review" and evidence is not None:
            groups.setdefault(link["project_id"], []).append({"link": link, "evidence": evidence})
    for project_id, items in groups.items():
        identity = next(i for i in identities if i.id == project_id)
        report["a01"].append(run_identity_agent(client, db, contracts, gateway, identity, identities, items, run_id))
    return report


def identify_metadata(
    client: MongoClient[dict[str, Any]],
    db: Database[dict[str, Any]],
    source: dict[str, Any],
    text: str,
    focus_project_ids: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Link a metadata-only source (a video) from its title and description. The text is not stored, so there are
    no paragraph segments and no evidence: the link only tells which project the item is about."""
    identities = load_identities(db)
    outcomes = match_text(identities, text, focus_project_ids, segments=[Segment("whole", text, None)])

    def write(session: ClientSession) -> list[dict[str, Any]]:
        return [link for link, _ in insert_outcomes(db, source, outcomes, session)]

    return run_in_transaction(client, write)


def identify_in_context(
    client: MongoClient[dict[str, Any]],
    db: Database[dict[str, Any]],
    contracts: ContractStore,
    source: dict[str, Any],
    context_link: dict[str, Any] | None,
    gateway: ModelGateway | None = None,
) -> dict[str, Any]:
    """A comment: matched on its own words first. One that names no project inherits its thread's accepted match
    (the video's, or for a reply its top comment's); if that match later leaves an accepted state, the inherited
    one returns to review with it (links.transition)."""
    report = identify_source(client, db, contracts, source, gateway=gateway)
    if report["links"] or context_link is None or context_link["status"] not in ACTIVE_STATUSES:
        return report
    text = source_text(db, source)
    if text is None:
        return report

    def write(session: ClientSession) -> dict[str, Any] | None:
        existing = db["ai_project_source_links"].find_one(
            {
                "project_id": context_link["project_id"],
                "source.id": source["id"],
                "source.revision": source["revision"],
                "segment_key": "whole",
            },
            session=session,
        )
        if existing is not None:
            return None
        doc = new_link(
            context_link["project_id"],
            source,
            "whole",
            None,
            "auto_accepted",
            context_link["phase"],
            {
                "method": "deterministic",
                "rule_score": None,
                "signals": [],
                "matched_alias": context_link["match"]["matched_alias"],
                "rationale": f"inherited from its thread's match {context_link['_id']}; the comment names no project",
            },
        )
        db["ai_project_source_links"].insert_one(doc, session=session)
        create_link_evidence(db, doc, source, text, session)
        audit.record(
            db,
            "source_link.created",
            "project_source_link",
            doc["_id"],
            audit.SYSTEM_ACTOR,
            details={"status": doc["status"], "segment": "whole", "inherited_from": context_link["_id"]},
            session=session,
        )
        return doc

    created = run_in_transaction(client, write)
    if created is not None:
        report["links"].append(
            {
                "link_id": created["_id"],
                "project_id": created["project_id"],
                "segment_key": "whole",
                "status": created["status"],
                "matched_alias": created["match"]["matched_alias"],
                "phase": created["phase"],
                "created": True,
                "inherited": True,
            }
        )
    return report
