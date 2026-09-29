"""Match corrections and alternate-name review (Step 04.6, 04.7; journeys J04, J05, J18)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, Depends, Query
from pymongo.database import Database

from app.api.deps import Principal, contract_body, contracts_dep, db_dep, known_id, require
from app.api.routes_ops import decode_cursor, encode_cursor
from app.contracts import ContractStore
from app.errors import ApiError
from app.identity.aliases import decide_alias, proposal_view
from app.identity.links import decide_link

router = APIRouter(prefix="/v1", tags=["identity"])
PROPOSAL_STATUSES = {"proposed", "approved", "rejected", "revoked"}


@router.post(
    "/project-source-links/{link_id}/decisions",
    operation_id="decideSourceLink",
    summary="Accept, reject, split or remap a project association",
)
def decide_source_link(
    link_id: str,
    body: Any = Body(...),
    principal: Principal = Depends(require("decideSourceLink")),
    db: Database[dict[str, Any]] = Depends(db_dep),
    contracts: ContractStore = Depends(contracts_dep),
) -> dict[str, Any]:
    known_id(link_id, "lnk")
    request = contract_body(contracts, body, "api.schema.json#/$defs/LinkDecisionRequest")
    return decide_link(db.client, db, contracts, link_id, request, principal.actor)


@router.get(
    "/projects/{project_id}/alias-proposals",
    operation_id="listAliasProposals",
    summary="Alternate-name proposals with evidence and collision result (D17)",
)
def list_alias_proposals(
    project_id: str,
    _: Principal = Depends(require("listAliasProposals")),
    db: Database[dict[str, Any]] = Depends(db_dep),
    status: str | None = Query(default=None),
    cursor: str | None = Query(default=None),
    limit: int = Query(default=25, ge=1, le=100),
) -> dict[str, Any]:
    known_id(project_id, "prj")
    if db["projects"].find_one({"_id": project_id}, {"_id": 1}) is None:
        raise ApiError(404, "not_found", "No such project")
    if status is not None and status not in PROPOSAL_STATUSES:
        raise ApiError(422, "validation_failed", "Unknown status", fields=[{"path": "status", "message": status[:50]}])
    query: dict[str, Any] = {"project_id": project_id}
    if status:
        query["status"] = status
    before = decode_cursor(cursor)
    if before:
        query["_id"] = {"$lt": before}
    rows = list(db["ai_alias_proposals"].find(query).sort("_id", -1).limit(limit + 1))
    more = len(rows) > limit
    rows = rows[:limit]
    return {
        "items": [proposal_view(r) for r in rows],
        "next_cursor": encode_cursor(rows[-1]["_id"]) if more and rows else None,
    }


@router.post(
    "/alias-proposals/{proposal_id}/decisions",
    operation_id="decideAliasProposal",
    summary="Approve (standalone or context-required), reject or revoke an alias",
)
def decide_alias_proposal(
    proposal_id: str,
    body: Any = Body(...),
    principal: Principal = Depends(require("decideAliasProposal")),
    db: Database[dict[str, Any]] = Depends(db_dep),
    contracts: ContractStore = Depends(contracts_dep),
) -> dict[str, Any]:
    known_id(proposal_id, "als")
    request = contract_body(contracts, body, "api.schema.json#/$defs/AliasDecisionRequest")
    return decide_alias(db.client, db, contracts, proposal_id, request, principal.actor)
