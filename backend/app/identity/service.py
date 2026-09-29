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
from app.identity.links import insert_outcomes
from app.identity.matching import match_text
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
