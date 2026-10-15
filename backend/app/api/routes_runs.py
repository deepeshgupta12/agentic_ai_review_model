"""Collection runs (Step 05; journeys J02, J16): start, list, read, cancel and follow a run's events."""

from __future__ import annotations

import json
import time
from collections.abc import Iterator
from typing import Any

from fastapi import APIRouter, Body, Depends, Header, Query
from fastapi.responses import StreamingResponse
from pymongo.database import Database

from app.api.deps import Principal, contract_body, contracts_dep, db_dep, known_id, require, settings_dep
from app.api.idempotency import HEADER, run_idempotent
from app.api.routes_ops import decode_cursor, encode_cursor
from app.config import Settings
from app.contracts import ContractStore, to_view
from app.errors import ApiError
from app.sources.collection import EVENTS, RUNS, cancel_run, run_view, start_run

router = APIRouter(prefix="/v1", tags=["runs"])
TERMINAL_STAGES = {"published", "insufficient_evidence", "cancelled", "analysing"}
STREAM_SECONDS = 25.0


@router.post("/projects/{project_id}/runs", operation_id="startRun", summary="Start a collection run", status_code=202)
def start_run_route(
    project_id: str,
    body: Any = Body(...),
    idempotency_key: str | None = Header(default=None, alias=HEADER),
    principal: Principal = Depends(require("startRun")),
    db: Database[dict[str, Any]] = Depends(db_dep),
    contracts: ContractStore = Depends(contracts_dep),
    settings: Settings = Depends(settings_dep),
) -> dict[str, Any]:
    known_id(project_id, "prj")
    request = contract_body(contracts, body, "api.schema.json#/$defs/RunRequest")
    return run_idempotent(
        db,
        operation_id=f"startRun:{project_id}",
        user_id=principal.user_id,
        key=idempotency_key,
        body=request,
        compute=lambda: start_run(db.client, db, settings, project_id, request, principal.actor),
    )


@router.get("/projects/{project_id}/runs", operation_id="listRuns", summary="Runs for a project, newest first")
def list_runs(
    project_id: str,
    _: Principal = Depends(require("listRuns")),
    db: Database[dict[str, Any]] = Depends(db_dep),
    cursor: str | None = Query(default=None),
    limit: int = Query(default=25, ge=1, le=100),
) -> dict[str, Any]:
    known_id(project_id, "prj")
    if db["projects"].find_one({"_id": project_id}, {"_id": 1}) is None:
        raise ApiError(404, "not_found", "No such project")
    query: dict[str, Any] = {"project_id": project_id}
    before = decode_cursor(cursor)
    if before:
        query["_id"] = {"$lt": before}
    rows = list(db[RUNS].find(query).sort("_id", -1).limit(limit + 1))
    more = len(rows) > limit
    rows = rows[:limit]
    return {
        "items": [run_view(r) for r in rows],
        "next_cursor": encode_cursor(rows[-1]["_id"]) if more and rows else None,
    }


@router.get("/runs/{run_id}", operation_id="getRun", summary="A run's stage, coverage and budget")
def get_run(
    run_id: str,
    _: Principal = Depends(require("getRun")),
    db: Database[dict[str, Any]] = Depends(db_dep),
) -> dict[str, Any]:
    known_id(run_id, "run")
    run = db[RUNS].find_one({"_id": run_id})
    if run is None:
        raise ApiError(404, "not_found", "No such run")
    return run_view(run)


@router.post("/runs/{run_id}/cancel", operation_id="cancelRun", summary="Cancel a run with a reason", status_code=202)
def cancel_run_route(
    run_id: str,
    body: Any = Body(...),
    principal: Principal = Depends(require("cancelRun")),
    db: Database[dict[str, Any]] = Depends(db_dep),
    contracts: ContractStore = Depends(contracts_dep),
) -> dict[str, Any]:
    known_id(run_id, "run")
    request = contract_body(contracts, body, "api.schema.json#/$defs/ReasonRequest")
    return cancel_run(db.client, db, contracts, run_id, request["reason"], principal.actor)


@router.post(
    "/runs/{run_id}/analysis",
    operation_id="continueAnalysis",
    summary="Continue a stopped analysis from its last checkpoint",
    status_code=202,
)
def continue_analysis_route(
    run_id: str,
    principal: Principal = Depends(require("continueAnalysis")),
    db: Database[dict[str, Any]] = Depends(db_dep),
    settings: Settings = Depends(settings_dep),
) -> dict[str, Any]:
    """After a stop on the model budget or model access: a new analyse job continues the run's graph from its last
    checkpoint and reuses every finished task, so nothing is paid twice. Refused while the budget has nothing left."""
    from app.agents.spend import SpendLedger
    from app.workflows.analysis import analyse_again

    known_id(run_id, "run")
    if db[RUNS].find_one({"_id": run_id}, {"_id": 1}) is None:
        raise ApiError(404, "not_found", "No such run")
    left = SpendLedger(db, settings).state()["left_usd"]
    if left <= 0.01:
        raise ApiError(
            409,
            "invalid_transition",  # the contract's ErrorCode: continuing needs budget left
            f"The model budget has ${max(left, 0):.2f} left; raise MODEL_BUDGET_USD in .env and restart the stack "
            "first",
        )
    try:
        out = analyse_again(db, run_id, principal.actor)
    except ValueError as exc:
        raise ApiError(409, "invalid_transition", str(exc)) from exc
    return {"job_id": out["job_id"], "run_id": run_id, "operation_id": None, "status_path": f"/v1/runs/{run_id}"}


def event_view(doc: dict[str, Any]) -> dict[str, Any]:
    view = to_view(doc, id_field="event_id")
    assert view is not None
    return view


@router.get(
    "/runs/{run_id}/events", operation_id="streamRunEvents", summary="Server-sent run events; resume with Last-Event-ID"
)
def stream_run_events(
    run_id: str,
    last_event_id: str | None = Header(default=None, alias="Last-Event-ID"),
    _: Principal = Depends(require("streamRunEvents")),
    db: Database[dict[str, Any]] = Depends(db_dep),
) -> StreamingResponse:
    known_id(run_id, "run")
    if db[RUNS].find_one({"_id": run_id}, {"_id": 1}) is None:
        raise ApiError(404, "not_found", "No such run")

    def events() -> Iterator[str]:
        after = last_event_id or ""
        deadline = time.monotonic() + STREAM_SECONDS
        yield "retry: 3000\n\n"
        while True:
            for doc in db[EVENTS].find({"run_id": run_id, "_id": {"$gt": after}}).sort("_id", 1):
                after = doc["_id"]
                view = event_view(doc)
                yield f"id: {doc['_id']}\nevent: {doc['type']}\ndata: {json.dumps(view, ensure_ascii=False)}\n\n"
            run = db[RUNS].find_one({"_id": run_id}, {"stage": 1})
            if run is None or run["stage"] in TERMINAL_STAGES or time.monotonic() > deadline:
                return
            time.sleep(1.0)

    return StreamingResponse(events(), media_type="text/event-stream", headers={"Cache-Control": "no-store"})
