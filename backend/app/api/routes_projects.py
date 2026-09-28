"""Project catalogue and configuration (Step 04.1; journeys J01, J18).

Import creates or updates catalogue records from the five-project input file; configuration changes need
the expected version. Aliases approved through proposals change only through alias decisions.
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
from app.db import utcnow
from app.errors import ApiError
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
    return {
        "project": {k: project[k] for k in ("slug", "project_name", "locality", "city")} | {"id": pid},
        "latest_run": None,
        "coverage": [],
        "pending_review": {
            "findings": 0,
            "review_excerpts": 0,
            "links": db["ai_project_source_links"].count_documents({"project_id": pid, "status": "needs_review"}),
            "alias_proposals": db["ai_alias_proposals"].count_documents({"project_id": pid, "status": "proposed"}),
            "corrections": 0,
        },
        "publication": {
            "serving_state": "unpublished",
            "approved_revision": None,
            "active_revision": None,
            "delivery_status": None,
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
