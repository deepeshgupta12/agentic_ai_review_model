"""Project catalogue and configuration (Steps 04.1 and 09.2; journeys J01, J18; D58).

Import creates or updates catalogue records from the five-project input file; a researcher can also add one project
from the console (same fields, state optional), which never updates an existing project. Configuration changes need
the expected version. Aliases approved through proposals change only through alias decisions. The portfolio row
reads the latest run, its coverage, the open review work and the publication state.
"""

from __future__ import annotations

import json
from datetime import timedelta
from typing import Any

from fastapi import APIRouter, Body, Depends, Header, Query
from pymongo.database import Database

from app import audit
from app.api.deps import Principal, contract_body, contracts_dep, db_dep, known_id, require, settings_dep
from app.api.idempotency import HEADER, run_idempotent
from app.api.routes_ops import decode_cursor, encode_cursor
from app.config import Settings
from app.contracts import ContractStore, to_view
from app.db import iso, utcnow
from app.errors import ApiError
from app.seed.normalise import match_key
from app.seed.projects import SeedError, import_projects

router = APIRouter(prefix="/v1", tags=["projects"])
PATCHABLE = ("negative_keywords", "input_languages", "refresh", "sources", "construction_status")


def config_view(doc: dict[str, Any]) -> dict[str, Any]:
    view = to_view(doc, id_field=None)
    assert view is not None
    return view


def project_view(doc: dict[str, Any]) -> dict[str, Any]:
    view = to_view({k: v for k, v in doc.items() if k != "match_key"})
    assert view is not None
    return view


def project_summary(db: Database[dict[str, Any]], project: dict[str, Any]) -> dict[str, Any]:
    pid = project["_id"]
    since = utcnow() - timedelta(days=30)
    spend = sum(
        r.get("estimated_cost_usd") or 0
        for r in db["ai_agent_runs"].find({"project_id": pid, "created_at": {"$gte": since}}, {"estimated_cost_usd": 1})
    )
    run = db["ai_runs"].find_one({"project_id": pid}, sort=[("created_at", -1)])
    state = db["ai_publication_state"].find_one({"project_id": pid, "locale": "en-IN"}) or {}
    operation = db["ai_publication_operations"].find_one({"project_id": pid}, sort=[("created_at", -1)])
    pending = {"review_status": "pending", "project_id": pid}
    return {
        "project": {k: project[k] for k in ("slug", "project_name", "locality", "city")} | {"id": pid},
        "latest_run": {"id": run["_id"], "stage": run["stage"], "updated_at": iso(run["updated_at"])} if run else None,
        "coverage": [to_view(c, id_field=None) for c in (run or {}).get("coverage", [])],
        "pending_review": {
            "findings": db["ai_findings"].count_documents(pending),
            "review_excerpts": db["ai_review_excerpts"].count_documents(pending),
            "links": db["ai_project_source_links"].count_documents({"project_id": pid, "status": "needs_review"}),
            "alias_proposals": db["ai_alias_proposals"].count_documents({"project_id": pid, "status": "proposed"}),
            "corrections": db["ai_corrections"].count_documents(
                {"project_id": pid, "status": {"$in": ["received", "in_review"]}}
            ),
        },
        "publication": {
            "serving_state": state.get("serving_state", "unpublished"),
            "approved_revision": (state.get("approved") or {}).get("revision"),
            "active_revision": (state.get("active") or {}).get("revision"),
            "delivery_status": operation["status"] if operation else None,
        },
        "stale": False,
        "spend_usd_30d": float(spend),
    }


@router.post(
    "/projects/import",
    operation_id="importProjects",
    summary="Import the five-project input file; creates or updates catalogue records",
)
def import_projects_route(
    body: Any = Body(...),
    idempotency_key: str | None = Header(default=None, alias=HEADER),
    principal: Principal = Depends(require("importProjects")),
    db: Database[dict[str, Any]] = Depends(db_dep),
    contracts: ContractStore = Depends(contracts_dep),
    settings: Settings = Depends(settings_dep),
) -> dict[str, Any]:
    data = contract_body(contracts, body, "catalogue.schema.json#/$defs/ProjectInputFile")

    def compute() -> dict[str, Any]:
        try:
            rows = import_projects(
                db.client, db, contracts, data, settings.seed_dir, actor=principal.actor, origin="import API"
            )
        except SeedError as exc:
            raise ApiError(409, "version_conflict", str(exc)) from exc
        return {
            "projects": [
                {k: r[k] for k in ("project_id", "slug", "project_name")} | {"created": r["outcome"] == "created"}
                for r in rows
            ]
        }

    return run_idempotent(
        db, operation_id="importProjects", user_id=principal.user_id, key=idempotency_key, body=data, compute=compute
    )


@router.post(
    "/projects",
    operation_id="createProject",
    summary="Add one project from the console (D58); never updates an existing project",
    status_code=201,
)
def create_project(
    body: Any = Body(...),
    idempotency_key: str | None = Header(default=None, alias=HEADER),
    principal: Principal = Depends(require("createProject")),
    db: Database[dict[str, Any]] = Depends(db_dep),
    contracts: ContractStore = Depends(contracts_dep),
    settings: Settings = Depends(settings_dep),
) -> dict[str, Any]:
    item = contract_body(contracts, body, "catalogue.schema.json#/$defs/ProjectInput")

    def compute() -> dict[str, Any]:
        if db["projects"].find_one({"match_key": match_key(item["project_name"], item["city"])}, {"_id": 1}):
            raise ApiError(
                409, "version_conflict", f"{item['project_name']} in {item['city']} is already in the catalogue"
            )
        try:
            rows = import_projects(
                db.client,
                db,
                contracts,
                {"projects": [item]},
                settings.seed_dir,
                actor=principal.actor,
                origin="console",
            )
        except SeedError as exc:
            raise ApiError(409, "version_conflict", str(exc)) from exc
        return {
            "projects": [
                {k: r[k] for k in ("project_id", "slug", "project_name")} | {"created": r["outcome"] == "created"}
                for r in rows
            ]
        }

    return run_idempotent(
        db, operation_id="createProject", user_id=principal.user_id, key=idempotency_key, body=item, compute=compute
    )


@router.get(
    "/projects", operation_id="listProjects", summary="Portfolio with run, review, coverage and publication summary"
)
def list_projects(
    _: Principal = Depends(require("listProjects")),
    db: Database[dict[str, Any]] = Depends(db_dep),
    cursor: str | None = Query(default=None),
    limit: int = Query(default=25, ge=1, le=100),
) -> dict[str, Any]:
    after = decode_cursor(cursor)
    query: dict[str, Any] = {"_id": {"$gt": after}} if after else {}
    rows = list(db["projects"].find(query).sort("_id", 1).limit(limit + 1))
    more = len(rows) > limit
    rows = rows[:limit]
    return {
        "items": [project_summary(db, p) for p in rows],
        "next_cursor": encode_cursor(rows[-1]["_id"]) if more and rows else None,
    }


@router.get("/projects/{project_id}", operation_id="getProject", summary="Project record and configuration")
def get_project(
    project_id: str,
    _: Principal = Depends(require("getProject")),
    db: Database[dict[str, Any]] = Depends(db_dep),
) -> dict[str, Any]:
    known_id(project_id, "prj")
    project = db["projects"].find_one({"_id": project_id})
    config = db["ai_project_configs"].find_one({"_id": project_id})
    if project is None or config is None:
        raise ApiError(404, "not_found", "No such project")
    return {"project": project_view(project), "config": config_view(config)}


@router.patch(
    "/projects/{project_id}", operation_id="updateProjectConfig", summary="Change configuration at an expected version"
)
def update_project_config(
    project_id: str,
    body: Any = Body(...),
    principal: Principal = Depends(require("updateProjectConfig")),
    db: Database[dict[str, Any]] = Depends(db_dep),
    contracts: ContractStore = Depends(contracts_dep),
    settings: Settings = Depends(settings_dep),
) -> dict[str, Any]:
    known_id(project_id, "prj")
    patch = contract_body(contracts, body, "api.schema.json#/$defs/ProjectConfigPatch")
    project = db["projects"].find_one({"_id": project_id})
    config = db["ai_project_configs"].find_one({"_id": project_id})
    if project is None or config is None:
        raise ApiError(404, "not_found", "No such project")
    if config["version"] != patch["expected_version"]:
        raise ApiError(
            409, "version_conflict", "The configuration changed; reload it", current_version=config["version"]
        )
    changes = {k: patch[k] for k in PATCHABLE if k in patch}
    if "sources" in changes:
        registry = json.loads((settings.seed_dir / "connectors.json").read_text(encoding="utf-8"))
        known = {c["id"] for c in registry["model_providers"] + registry["connectors"]}
        unknown = [s["connector_id"] for s in changes["sources"] if s["connector_id"] not in known]
        if unknown:
            raise ApiError(
                422,
                "validation_failed",
                "Unknown connector",
                fields=[{"path": "sources", "message": ", ".join(unknown)}],
            )
    if "construction_status" in changes:
        registrations = {r["id_normalised"] for r in project["rera_registrations"]}
        wrong = [
            r["applies_to"]["rera_id"]
            for r in changes["construction_status"]
            if r["applies_to"]["kind"] == "phase" and r["applies_to"]["rera_id"] not in registrations
        ]
        if wrong:
            raise ApiError(
                422,
                "validation_failed",
                "A status record names a registration the project does not have",
                fields=[{"path": "construction_status", "message": ", ".join(wrong)}],
            )
    now = utcnow()
    result = db["ai_project_configs"].update_one(
        {"_id": project_id, "version": config["version"]},
        {"$set": {**changes, "updated_at": now, "updated_by": principal.actor}, "$inc": {"version": 1}},
    )
    if result.modified_count != 1:
        latest = db["ai_project_configs"].find_one({"_id": project_id}) or config
        raise ApiError(
            409, "version_conflict", "The configuration changed; reload it", current_version=latest["version"]
        )
    audit.record(
        db,
        "project_config.updated",
        "project",
        project_id,
        principal.actor,
        details={"fields": ",".join(sorted(changes))},
    )
    updated = db["ai_project_configs"].find_one({"_id": project_id})
    assert updated is not None
    return config_view(updated)
