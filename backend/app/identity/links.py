"""Project-source links (ProjectSourceLink): creation from match outcomes, state-machine transitions and
moderator decisions (Step 04.5, 04.6; journeys J04, J05, J18).

One source revision is stored once; each project association is its own link, so a comparison article or
video links to several projects through distinct segments. Every status change follows state_machines.json
and the expected version. Leaving an accepted state enqueues dependency invalidation.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from pymongo import MongoClient
from pymongo.client_session import ClientSession
from pymongo.database import Database
from pymongo.errors import DuplicateKeyError

from app import audit
from app.contracts import ContractStore, to_view
from app.db import run_in_transaction, utcnow
from app.decisions import record_decision
from app.errors import ApiError
from app.identity.evidence import create_link_evidence
from app.identity.intake import source_text
from app.identity.matching import MatchOutcome
from app.identity.text import sha256_text
from app.ids import new_id
from app.jobs import queue

ACTIVE_STATUSES = {"auto_accepted", "accepted"}
SEGMENT_KEY = re.compile(r"^(c|t):(\d+)-(\d+)$")


def link_view(doc: dict[str, Any]) -> dict[str, Any]:
    view = to_view(doc)
    assert view is not None
    return view


def new_link(
    project_id: str,
    source: dict[str, Any],
    segment_key: str,
    segment_anchor: dict[str, Any] | None,
    status: str,
    phase: dict[str, Any],
    match: dict[str, Any],
    decided_by: str | None = None,
) -> dict[str, Any]:
    return {
        "_id": new_id("lnk"),
        "project_id": project_id,
        "source": {"id": source["id"], "revision": source["revision"]},
        "segment_key": segment_key,
        "segment_anchor": segment_anchor,
        "status": status,
        "phase": phase,
        "match": match,
        "decided_by": decided_by,
        "superseded_by": [],
        "version": 1,
        "created_at": utcnow(),
    }


def insert_outcomes(
    db: Database[dict[str, Any]],
    source: dict[str, Any],
    outcomes: list[MatchOutcome],
    session: ClientSession | None = None,
) -> list[tuple[dict[str, Any], bool]]:
    """Create a link per outcome; an existing link for the same project and segment is kept as it is."""
    results: list[tuple[dict[str, Any], bool]] = []
    for outcome in outcomes:
        key = {
            "project_id": outcome.project_id,
            "source.id": source["id"],
            "source.revision": source["revision"],
            "segment_key": outcome.segment.key,
        }
        existing = db["ai_project_source_links"].find_one(key, session=session)
        if existing is not None:
            results.append((existing, False))
            continue
        doc = new_link(
            outcome.project_id,
            source,
            outcome.segment.key,
            outcome.segment.anchor,
            outcome.status,
            outcome.phase,
            {
                "method": "deterministic",
                "rule_score": outcome.rule_score,
                "signals": outcome.signals,
                "matched_alias": outcome.matched_alias,
                "rationale": outcome.rationale,
            },
        )
        db["ai_project_source_links"].insert_one(doc, session=session)
        results.append((doc, True))
    return results


def enqueue_invalidation(db: Database[dict[str, Any]], link: dict[str, Any], session: ClientSession | None) -> None:
    """Evidence on a link that left an accepted state is no longer eligible; dependants are re-reviewed."""
    queue.enqueue(
        db,
        "invalidate_dependencies",
        f"invalidate_dependencies:link:{link['_id']}:v{link['version']}",
        project_id=link["project_id"],
        session=session,
    )


def transition(
    db: Database[dict[str, Any]],
    contracts: ContractStore,
    link: dict[str, Any],
    to_status: str,
    actor_role: str,
    *,
    session: ClientSession | None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Move a link to a new status at its current version; returns the updated record."""
    if not contracts.transition_allowed("source_link", link["status"], to_status, actor_role):
        raise ApiError(
            409, "invalid_transition", f"A {actor_role} cannot move a link from {link['status']} to {to_status}"
        )
    changes = {"status": to_status, **(extra or {})}
    result = db["ai_project_source_links"].update_one(
        {"_id": link["_id"], "version": link["version"]},
        {"$set": changes, "$inc": {"version": 1}},
        session=session,
    )
    if result.modified_count != 1:
        raise ApiError(409, "version_conflict", "The link changed; reload it", current_version=link["version"] + 1)
    updated = {**link, **changes, "version": link["version"] + 1}
    if link["status"] in ACTIVE_STATUSES and to_status not in ACTIVE_STATUSES:
        enqueue_invalidation(db, updated, session)
    return updated


def return_to_review(
    db: Database[dict[str, Any]],
    contracts: ContractStore,
    query: dict[str, Any],
    reason: str,
    session: ClientSession | None,
) -> list[str]:
    """System transition back to needs_review (an alias was revoked, D35); dependants are invalidated."""
    moved: list[str] = []
    for link in db["ai_project_source_links"].find(
        {**query, "status": {"$in": sorted(ACTIVE_STATUSES)}}, session=session
    ):
        transition(db, contracts, link, "needs_review", "system", session=session)
        audit.record(
            db,
            "source_link.returned_to_review",
            "project_source_link",
            link["_id"],
            audit.SYSTEM_ACTOR,
            details={"reason": reason},
            session=session,
        )
        moved.append(link["_id"])
    return moved


def _phase_for(project: dict[str, Any], rera_id: str | None) -> dict[str, Any]:
    registrations = {r["id_normalised"] for r in project["rera_registrations"]}
    if len(registrations) <= 1:
        return {"rera_id": None, "certainty": "not_applicable"}
    if rera_id is None:
        return {"rera_id": None, "certainty": "unknown"}
    if rera_id not in registrations:
        raise ApiError(
            422,
            "validation_failed",
            "That RERA registration does not belong to the project",
            fields=[{"path": "phase_rera_id", "message": "not one of the project's registrations"}],
        )
    return {"rera_id": rera_id, "certainty": "known"}


def _check_split_segment(item: dict[str, Any], text: str | None) -> None:
    m = SEGMENT_KEY.match(item["segment_key"])
    anchor = item["anchor"]
    bad = ApiError(
        422,
        "validation_failed",
        "A split segment does not match the source",
        fields=[
            {
                "path": "split_segments",
                "message": f"{item['segment_key']}: anchor and key disagree or fall outside the text",
            }
        ],
    )
    if m is None:
        raise bad
    kind, start, end = m.group(1), int(m.group(2)), int(m.group(3))
    if kind == "c":
        if anchor.get("kind") != "text" or (anchor["start"], anchor["end"]) != (start, end) or text is None:
            raise bad
        if not 0 <= start < end <= len(text) or anchor["excerpt_sha256"] != sha256_text(text[start:end]):
            raise bad
    elif anchor.get("kind") != "time" or (anchor.get("start_ms"), anchor.get("end_ms")) != (start, end):
        raise bad


def decide_link(
    client: MongoClient[dict[str, Any]],
    db: Database[dict[str, Any]],
    contracts: ContractStore,
    seed_dir: Path,
    link_id: str,
    body: dict[str, Any],
    actor: dict[str, Any],
) -> dict[str, Any]:
    """Accept, reject, split or remap one link at its expected version (LinkDecisionRequest)."""
    role = actor["role"]

    def write(session: ClientSession) -> dict[str, Any]:
        link = db["ai_project_source_links"].find_one({"_id": link_id}, session=session)
        if link is None:
            raise ApiError(404, "not_found", "No such link")
        if link["version"] != body["expected_version"]:
            raise ApiError(409, "version_conflict", "The link changed; reload it", current_version=link["version"])
        project = db["projects"].find_one({"_id": link["project_id"]}, session=session)
        assert project is not None
        action = body["action"]
        decision_id = record_decision(
            db,
            target_type="project_source_link",
            target_id=link_id,
            revision=None,
            action=action,
            reason=body["reason"],
            actor=actor,
            session=session,
        )
        if action in ("accept", "reject"):
            extra: dict[str, Any] = {"decided_by": decision_id}
            if action == "accept" and body["phase_rera_id"] is not None:
                extra["phase"] = _phase_for(project, body["phase_rera_id"])
            to = "accepted" if action == "accept" else "rejected"
            updated = transition(db, contracts, link, to, role, session=session, extra=extra)
        else:
            source = db["ai_sources"].find_one(link["source"], session=session)
            text = source_text(db, source, session) if source else None
            if action == "split":
                targets = [(s["project_id"], s["segment_key"], s["anchor"]) for s in body["split_segments"]]
                for s in body["split_segments"]:
                    _check_split_segment(s, text)
            else:
                if body["remap_project_id"] == link["project_id"]:
                    raise ApiError(422, "validation_failed", "Remap needs a different project")
                targets = [(body["remap_project_id"], link["segment_key"], link["segment_anchor"])]
            new_ids: list[str] = []
            for project_id, segment_key, anchor in targets:
                target_project = db["projects"].find_one({"_id": project_id}, session=session)
                if target_project is None:
                    raise ApiError(422, "validation_failed", "Unknown project in the decision")
                phase_rera = body["phase_rera_id"] if project_id == link["project_id"] else None
                doc = new_link(
                    project_id,
                    link["source"],
                    segment_key,
                    anchor,
                    "accepted",
                    _phase_for(target_project, phase_rera),
                    {
                        "method": "moderator",
                        "rule_score": None,
                        "signals": [],
                        "matched_alias": None,
                        "rationale": f"{action} by a moderator: {body['reason']}",
                    },
                    decided_by=decision_id,
                )
                if db["ai_project_source_links"].find_one(
                    {
                        "project_id": project_id,
                        "source.id": link["source"]["id"],
                        "source.revision": link["source"]["revision"],
                        "segment_key": segment_key,
                    },
                    session=session,
                ):
                    raise ApiError(409, "version_conflict", f"{segment_key} is already linked to that project")
                try:
                    db["ai_project_source_links"].insert_one(doc, session=session)
                except DuplicateKeyError as exc:
                    raise ApiError(409, "version_conflict", "That segment is already linked") from exc
                if source is not None and text is not None:
                    create_link_evidence(db, doc, source, text, session)
                new_ids.append(doc["_id"])
            updated = transition(
                db,
                contracts,
                link,
                "superseded",
                role,
                session=session,
                extra={"decided_by": decision_id, "superseded_by": new_ids},
            )
        audit.record(
            db,
            f"source_link.{action}",
            "project_source_link",
            link_id,
            actor,
            details={"from": link["status"], "to": updated["status"]},
            session=session,
        )
        return updated

    return link_view(run_in_transaction(client, write))
