"""Source-policy administration (docs/02 ai_source_policies; D38). Versions are immutable; a change is a new
version, created and accepted by an administrator, and narrowing rights triggers a dependency re-check."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, Depends, Query
from pymongo.database import Database

from app.api.deps import Principal, contract_body, contracts_dep, db_dep, require
from app.api.routes_ops import decode_cursor, encode_cursor
from app.contracts import ContractStore
from app.sources.policies import COLLECTION, create_version, policy_view

router = APIRouter(prefix="/v1", tags=["admin"])


@router.get("/admin/source-policies", operation_id="listSourcePolicies", summary="Source policies, every version")
def list_source_policies(
    _: Principal = Depends(require("listSourcePolicies")),
    db: Database[dict[str, Any]] = Depends(db_dep),
    cursor: str | None = Query(default=None),
    limit: int = Query(default=25, ge=1, le=100),
) -> dict[str, Any]:
    after = decode_cursor(cursor)
    query: dict[str, Any] = {"_id": {"$gt": after}} if after else {}
    rows = list(db[COLLECTION].find(query).sort("_id", 1).limit(limit + 1))
    more = len(rows) > limit
    rows = rows[:limit]
    return {
        "items": [policy_view(r) for r in rows],
        "next_cursor": encode_cursor(rows[-1]["_id"]) if more and rows else None,
    }


@router.post(
    "/admin/source-policies",
    operation_id="createSourcePolicyVersion",
    summary="Create the next immutable version of a policy family",
    status_code=201,
)
def create_source_policy_version(
    body: Any = Body(...),
    principal: Principal = Depends(require("createSourcePolicyVersion")),
    db: Database[dict[str, Any]] = Depends(db_dep),
    contracts: ContractStore = Depends(contracts_dep),
) -> dict[str, Any]:
    request = contract_body(contracts, body, "api.schema.json#/$defs/PolicyVersionRequest")
    return create_version(db.client, db, contracts, request, principal.actor)
