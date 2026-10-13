"""Publication and the public read (docs/03 page-renderer adapter; docs/05 activation algorithm).

Publishers activate an approved revision, roll back to an earlier eligible one or unpublish; each is an operation
with its own idempotency key, recorded with activation and verified-delivery times separately (202: delivery is
verified by a worker). The public read returns only the active, eligible revision, or 404.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, Depends, Header
from pymongo.database import Database

from app.api.deps import Principal, contract_body, contracts_dep, db_dep, known_id, require
from app.api.idempotency import HEADER
from app.contracts import ContractStore
from app.errors import ApiError
from app.publication import service

router = APIRouter(prefix="/v1", tags=["publication"])


@router.get(
    "/projects/{project_id}/publication",
    operation_id="getPublicationState",
    summary="Approved, active and verified revisions with recent operations",
)
def get_publication_state(
    project_id: str,
    _: Principal = Depends(require("getPublicationState")),
    db: Database[dict[str, Any]] = Depends(db_dep),
) -> dict[str, Any]:
    known_id(project_id, "prj")
    if db["projects"].find_one({"_id": project_id}, {"_id": 1}) is None:
        raise ApiError(404, "not_found", "No such project")
    return service.state_view(db, project_id)


@router.post("/publications", operation_id="publish", summary="Publish the approved revision", status_code=202)
def publish(
    body: Any = Body(...),
    idempotency_key: str | None = Header(default=None, alias=HEADER),
    principal: Principal = Depends(require("publish")),
    db: Database[dict[str, Any]] = Depends(db_dep),
    contracts: ContractStore = Depends(contracts_dep),
) -> dict[str, Any]:
    request = contract_body(contracts, body, "api.schema.json#/$defs/PublicationRequest")
    return service.publish(db, contracts, request, idempotency_key, principal.actor)


@router.get("/publications/{operation_id}", operation_id="getPublication", summary="One publication operation")
def get_publication(
    operation_id: str,
    _: Principal = Depends(require("getPublication")),
    db: Database[dict[str, Any]] = Depends(db_dep),
) -> dict[str, Any]:
    known_id(operation_id, "pub")
    doc = db[service.OPERATIONS].find_one({"_id": operation_id})
    if doc is None:
        raise ApiError(404, "not_found", "Not found")
    return service.operation_view(doc)


@router.post(
    "/publications/{operation_id}/rollback",
    operation_id="rollbackPublication",
    summary="Restore an earlier revision that is still eligible",
    status_code=202,
)
def rollback_publication(
    operation_id: str,
    body: Any = Body(...),
    idempotency_key: str | None = Header(default=None, alias=HEADER),
    principal: Principal = Depends(require("rollbackPublication")),
    db: Database[dict[str, Any]] = Depends(db_dep),
    contracts: ContractStore = Depends(contracts_dep),
) -> dict[str, Any]:
    known_id(operation_id, "pub")
    request = contract_body(contracts, body, "api.schema.json#/$defs/RollbackRequest")
    return service.rollback(db, contracts, operation_id, request, idempotency_key, principal.actor)


@router.post(
    "/projects/{project_id}/unpublish",
    operation_id="unpublishProject",
    summary="Stop serving the module; the page shows its empty state",
    status_code=202,
)
def unpublish_project(
    project_id: str,
    body: Any = Body(...),
    idempotency_key: str | None = Header(default=None, alias=HEADER),
    principal: Principal = Depends(require("unpublishProject")),
    db: Database[dict[str, Any]] = Depends(db_dep),
    contracts: ContractStore = Depends(contracts_dep),
) -> dict[str, Any]:
    known_id(project_id, "prj")
    request = contract_body(contracts, body, "api.schema.json#/$defs/UnpublishRequest")
    return service.unpublish(db, contracts, project_id, request, idempotency_key, principal.actor)


@router.get(
    "/public/projects/{slug}/insights",
    operation_id="getPublicInsights",
    summary="The active, eligible revision of a project's module (never a draft)",
)
def get_public_insights(slug: str, db: Database[dict[str, Any]] = Depends(db_dep)) -> dict[str, Any]:
    insights = service.public_insights(db, slug)
    if insights is None:
        raise ApiError(404, "not_found", "Nothing is published for this project")
    return insights
