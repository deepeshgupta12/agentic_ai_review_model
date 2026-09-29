"""Alternate-name and phase-name proposals (Step 04.7, D17, docs/04).

A01 proposes names it saw in the supplied evidence. The backend, not the model, decides what is kept:
- every cited evidence ID must come from the task's input, and the alias must appear in a cited span;
- at least one cited, usable span must show the alias with a strong identifier (a RERA ID of the project,
  the project name, or the developer with the locality; official registry records count as official pages);
- proposals are deduplicated per project and normalised form; independent origins are counted;
- a deterministic collision check compares the alias with every other catalogue project and generic terms.
Proposals do nothing until a researcher or moderator approves them. Approval writes the alias to the
project configuration at its current version; revoking removes it and sends the matches it produced back
to review. Rejected proposals are kept so the same name is not proposed again.
"""

from __future__ import annotations

from typing import Any

from pymongo import MongoClient
from pymongo.client_session import ClientSession
from pymongo.database import Database

from app import audit
from app.contracts import ContractStore, to_view
from app.db import run_in_transaction, utcnow
from app.decisions import record_decision
from app.errors import ApiError
from app.identity.catalogue import ProjectIdentity
from app.identity.evidence import usable_for_identity
from app.identity.links import return_to_review
from app.identity.rules import GENERIC_TERMS
from app.identity.text import contains, normalise_rera_id, normalise_text, rera_ids_in
from app.ids import new_id

STRONG_PRIORITY = ["rera_id", "known_project_name", "developer_and_locality", "official_page"]


def collision_check(alias_norm: str, identity: ProjectIdentity, others: list[ProjectIdentity]) -> dict[str, Any]:
    """none, colliding (shares a name with another catalogue project) or generic (place, developer or common words)."""
    colliding = []
    for other in others:
        names = {other.name_norm, *(a.normalised for a in other.aliases)}
        if any(alias_norm == n or contains(n, alias_norm) or contains(alias_norm, n) for n in names):
            colliding.append(other.id)
    if colliding:
        return {
            "status": "colliding",
            "colliding_project_ids": colliding,
            "reason": "shares a name with another catalogue project",
        }
    tokens = alias_norm.split()
    place_and_developer = {
        *(t for v in identity.locality_variants + identity.city_variants for t in v.split()),
        *((identity.micromarket_norm or "").split()),
        *((identity.developer_norm or "").split()),
    }
    if all(t in GENERIC_TERMS or t in place_and_developer for t in tokens):
        return {"status": "generic", "colliding_project_ids": [], "reason": "only a place, developer or common words"}
    if len(tokens) == 1 and len(tokens[0]) < 4:
        return {"status": "generic", "colliding_project_ids": [], "reason": "too short to identify a project alone"}
    return {"status": "none", "colliding_project_ids": [], "reason": None}


def strong_identifier_kind(
    alias_norm: str, excerpt: str, identity: ProjectIdentity, source_kind: str | None = None
) -> str | None:
    """Which strong identifier this span shows next to the alias, if any (backend rule, docs/04)."""
    norm = normalise_text(excerpt)
    if not contains(norm, alias_norm):
        return None
    found: list[str] = []
    if rera_ids_in(excerpt) & identity.rera_ids:
        found.append("rera_id")
    if identity.name_norm != alias_norm and contains(norm, identity.name_norm):
        found.append("known_project_name")
    developer = identity.developer_norm and contains(norm, identity.developer_norm)
    if developer and any(contains(norm, v) for v in identity.locality_variants):
        found.append("developer_and_locality")
    if source_kind == "registration_record":
        found.append("official_page")
    return next((k for k in STRONG_PRIORITY if k in found), None)


def record_proposals(
    db: Database[dict[str, Any]],
    identity: ProjectIdentity,
    others: list[ProjectIdentity],
    proposals: list[dict[str, Any]],
    allowed_evidence: dict[str, dict[str, Any]],
    task_id: str,
    session: ClientSession | None = None,
) -> list[dict[str, Any]]:
    """Apply the backend rules to A01 alias proposals. Returns one report row per proposal."""
    approved = {a.normalised for a in identity.aliases} | {identity.name_norm}
    report: list[dict[str, Any]] = []
    for item in proposals:
        alias_text = " ".join(str(item.get("alias_text", "")).split())
        alias_norm = normalise_text(alias_text)
        row: dict[str, Any] = {"alias_text": alias_text, "outcome": "rejected", "reason": None, "proposal_id": None}
        report.append(row)
        cited = list(dict.fromkeys(item.get("evidence_ids", [])))
        if not alias_norm:
            row["reason"] = "empty alias"
            continue
        if not cited or any(e not in allowed_evidence for e in cited):
            row["reason"] = "cites evidence outside the task input"
            continue
        docs = [allowed_evidence[e] for e in cited]
        if not any(contains(normalise_text(d["excerpt_text"] or ""), alias_norm) for d in docs):
            row["reason"] = "the alias does not appear in the cited evidence"
            continue
        if alias_norm in approved:
            row.update(outcome="skipped", reason="already an approved alias")
            continue
        existing = db["ai_alias_proposals"].find_one(
            {"project_id": identity.id, "normalised": alias_norm}, session=session
        )
        if existing is not None and existing["status"] != "proposed":
            row.update(outcome="skipped", reason=f"already {existing['status']}", proposal_id=existing["_id"])
            continue
        strong: tuple[str, dict[str, Any]] | None = None
        for doc in docs:
            if not usable_for_identity(db, doc, session):
                continue
            source = db["ai_sources"].find_one(doc["source"], session=session)
            kind = strong_identifier_kind(
                alias_norm, doc["excerpt_text"], identity, source["source_kind"] if source else None
            )
            if kind and (strong is None or STRONG_PRIORITY.index(kind) < STRONG_PRIORITY.index(strong[0])):
                strong = (kind, doc)
        if strong is None:
            row["reason"] = "no cited, usable span shows the alias with a strong identifier"
            continue
        target_rera = normalise_rera_id(item["target_rera_id"]) if item.get("target_rera_id") else None
        target = (
            {"kind": "phase", "rera_id": target_rera}
            if target_rera in identity.rera_ids
            else {"kind": "project", "rera_id": None}
        )
        refs = [{"id": d["id"], "revision": d["revision"]} for d in docs]
        if existing is not None:
            merged = existing["evidence_refs"] + [r for r in refs if r not in existing["evidence_refs"]]
            origins = _independent_origins(db, merged, session)
            db["ai_alias_proposals"].update_one(
                {"_id": existing["_id"], "version": existing["version"]},
                {"$set": {"evidence_refs": merged, "independent_origin_count": origins}, "$inc": {"version": 1}},
                session=session,
            )
            row.update(outcome="merged", reason=None, proposal_id=existing["_id"])
            continue
        proposal_id = new_id("als")
        db["ai_alias_proposals"].insert_one(
            {
                "_id": proposal_id,
                "project_id": identity.id,
                "alias_text": alias_text,
                "normalised": alias_norm,
                "alias_type": item["alias_type"],
                "target": target,
                "evidence_refs": refs,
                "strong_identifier": {
                    "kind": strong[0],
                    "evidence_ref": {"id": strong[1]["id"], "revision": strong[1]["revision"]},
                },
                "independent_origin_count": _independent_origins(db, refs, session),
                "collision": collision_check(alias_norm, identity, others),
                "status": "proposed",
                "decision": None,
                "proposed_by_task": task_id,
                "version": 1,
                "created_at": utcnow(),
            },
            session=session,
        )
        row.update(outcome="proposed", reason=None, proposal_id=proposal_id)
    return report


def _independent_origins(
    db: Database[dict[str, Any]], refs: list[dict[str, Any]], session: ClientSession | None
) -> int:
    """Copies of one origin count once: by origin cluster when known, else by source."""
    origins = set()
    for ref in refs:
        doc = db["ai_evidence"].find_one({"id": ref["id"], "revision": ref["revision"]}, session=session)
        if doc is not None:
            cluster = doc.get("origin_cluster")
            origins.add(("cluster", cluster["id"]) if cluster else ("source", doc["source"]["id"]))
    return max(1, len(origins))


def proposal_view(doc: dict[str, Any]) -> dict[str, Any]:
    view = to_view(doc)
    assert view is not None
    return view


def decide_alias(
    client: MongoClient[dict[str, Any]],
    db: Database[dict[str, Any]],
    contracts: ContractStore,
    proposal_id: str,
    body: dict[str, Any],
    actor: dict[str, Any],
) -> dict[str, Any]:
    """Approve (standalone or context-required), reject or revoke at the expected version (AliasDecisionRequest)."""
    to_status = {"approve": "approved", "reject": "rejected", "revoke": "revoked"}[body["action"]]

    def write(session: ClientSession) -> dict[str, Any]:
        proposal = db["ai_alias_proposals"].find_one({"_id": proposal_id}, session=session)
        if proposal is None:
            raise ApiError(404, "not_found", "No such alias proposal")
        if proposal["version"] != body["expected_version"]:
            raise ApiError(
                409, "version_conflict", "The proposal changed; reload it", current_version=proposal["version"]
            )
        if not contracts.transition_allowed("alias_proposal", proposal["status"], to_status, actor["role"]):
            raise ApiError(
                409, "invalid_transition", f"Cannot {body['action']} a proposal that is {proposal['status']}"
            )
        mode = body["mode"]
        if body["action"] == "approve" and proposal["collision"]["status"] != "none" and mode != "context_required":
            raise ApiError(
                422,
                "validation_failed",
                "A colliding or generic alias can only be approved as context-required",
                fields=[{"path": "mode", "message": f"collision check: {proposal['collision']['status']}"}],
            )
        if body["action"] == "revoke":
            mode = proposal["decision"]["mode"]
        decision_id = record_decision(
            db,
            target_type="alias_proposal",
            target_id=proposal_id,
            revision=None,
            action=body["action"],
            reason=body["reason"],
            actor=actor,
            session=session,
        )
        decision = {"decision_id": decision_id, "mode": mode if to_status != "rejected" else None}
        config = db["ai_project_configs"].find_one({"_id": proposal["project_id"]}, session=session)
        assert config is not None
        returned: list[str] = []
        if body["action"] == "approve":
            alias = {
                "text": proposal["alias_text"],
                "normalised": proposal["normalised"],
                "target": proposal["target"],
                "mode": mode,
                "origin": "approved_proposal",
                "proposal_id": proposal_id,
            }
            if any(a["normalised"] == proposal["normalised"] for a in config["aliases"]):
                raise ApiError(409, "version_conflict", "That name is already an alias of the project")
            _update_config(db, config, {"$push": {"aliases": alias}}, actor, session)
        elif body["action"] == "revoke":
            _update_config(db, config, {"$pull": {"aliases": {"proposal_id": proposal_id}}}, actor, session)
            returned = return_to_review(
                db,
                contracts,
                {"project_id": proposal["project_id"], "match.matched_alias": proposal["alias_text"]},
                f"alias '{proposal['alias_text']}' revoked",
                session,
            )
        db["ai_alias_proposals"].update_one(
            {"_id": proposal_id, "version": proposal["version"]},
            {"$set": {"status": to_status, "decision": decision}, "$inc": {"version": 1}},
            session=session,
        )
        audit.record(
            db,
            f"alias_proposal.{to_status}",
            "alias_proposal",
            proposal_id,
            actor,
            details={
                "alias": proposal["alias_text"],
                "mode": decision["mode"] or "none",
                "links_returned": len(returned),
            },
            session=session,
        )
        return {**proposal, "status": to_status, "decision": decision, "version": proposal["version"] + 1}

    return proposal_view(run_in_transaction(client, write))


def _update_config(
    db: Database[dict[str, Any]],
    config: dict[str, Any],
    change: dict[str, Any],
    actor: dict[str, Any],
    session: ClientSession,
) -> None:
    result = db["ai_project_configs"].update_one(
        {"_id": config["_id"], "version": config["version"]},
        {**change, "$inc": {"version": 1}, "$set": {"updated_at": utcnow(), "updated_by": actor}},
        session=session,
    )
    if result.modified_count != 1:
        raise ApiError(409, "version_conflict", "The project configuration changed; try again")
