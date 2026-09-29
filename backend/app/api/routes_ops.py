"""Operations views available in Step 03: summary, connector health and jobs."""

from __future__ import annotations

import base64
import json
from typing import Any

from fastapi import APIRouter, Depends, Query
from pymongo.database import Database

from app.api.deps import Principal, db_dep, require, settings_dep
from app.config import Settings
from app.errors import ApiError
from app.jobs.queue import job_view

router = APIRouter(prefix="/v1", tags=["ops"])


def encode_cursor(last_id: str) -> str:
    return base64.urlsafe_b64encode(json.dumps({"before": last_id}).encode()).decode()


def decode_cursor(cursor: str | None) -> str | None:
    if not cursor:
        return None
    try:
        return str(json.loads(base64.urlsafe_b64decode(cursor.encode()).decode())["before"])
    except (ValueError, KeyError) as exc:
        raise ApiError(
            422, "validation_failed", "Invalid cursor", fields=[{"path": "cursor", "message": "not a valid cursor"}]
        ) from exc


@router.get("/ops/summary", operation_id="getOpsSummary", summary="Freshness, failures, backlogs and model usage")
def ops_summary(
    _: Principal = Depends(require("getOpsSummary")),
    db: Database[dict[str, Any]] = Depends(db_dep),
) -> dict[str, Any]:
    failed = {
        row["_id"]: row["n"]
        for row in db["ai_jobs"].aggregate(
            [{"$match": {"status": "failed"}}, {"$group": {"_id": "$project_id", "n": {"$sum": 1}}}]
        )
    }
    usage = list(
        db["ai_agent_runs"].aggregate(
            [
                {
                    "$group": {
                        "_id": "$agent",
                        "calls": {"$sum": 1},
                        "input_tokens": {"$sum": {"$ifNull": ["$usage.input_tokens", 0]}},
                        "output_tokens": {"$sum": {"$ifNull": ["$usage.output_tokens", 0]}},
                        "cost_usd": {"$sum": {"$ifNull": ["$estimated_cost_usd", 0]}},
                    }
                },
                {"$sort": {"_id": 1}},
            ]
        )
    )
    return {
        "projects": [
            {
                "project_id": project["_id"],
                "newest_evidence_at": None,
                "active_revision_age_days": None,
                "stale": False,
                "failed_jobs": failed.get(project["_id"], 0),
                "spend_usd_30d": 0.0,
            }
            for project in db["projects"].find({}, {"_id": 1}).sort("_id", 1)
        ],
        "delivery_pending": 0,
        "deletion_backlog": 0,
        "model_usage": [
            {
                "agent": row["_id"],
                "calls": row["calls"],
                "input_tokens": row["input_tokens"],
                "output_tokens": row["output_tokens"],
                "cost_usd": float(row["cost_usd"]),
            }
            for row in usage
        ],
    }


@router.get(
    "/connectors/health", operation_id="getConnectorHealth", summary="Entitlements, last success, quota and safe errors"
)
def connector_health(
    _: Principal = Depends(require("getConnectorHealth")),
    db: Database[dict[str, Any]] = Depends(db_dep),
    settings: Settings = Depends(settings_dep),
) -> dict[str, Any]:
    """Status comes from the registry (live only after a recorded demonstration); success, errors and quota from
    what the collectors actually did."""
    from app.db import iso, utcnow
    from app.sources import quota

    registry = json.loads((settings.seed_dir / "connectors.json").read_text(encoding="utf-8"))
    buckets = {"brave_search": "requests", "youtube_data_api": "search"}
    now = utcnow()
    out = []
    for item in registry["model_providers"] + registry["connectors"]:
        states = list(
            db["ai_connector_state"].find({"connector_id": item["id"]}, {"last_success_at": 1, "last_error": 1})
        )
        successes = [s["last_success_at"] for s in states if s.get("last_success_at")]
        errors = [s["last_error"] for s in states if s.get("last_error")]
        latest = max(errors, key=lambda e: e["at"]) if errors else None
        usage = quota.usage(db, settings, item["id"], buckets[item["id"]], now) if item["id"] in buckets else None
        out.append(
            {
                "connector_id": item["id"],
                "status": item["status"],
                "last_verified": item["last_verified"],
                "last_success_at": iso(max(successes)) if successes else None,
                "quota": {"limit": usage["limit"], "used": usage["used"], "resets_at": iso(usage["resets_at"])}
                if usage
                else {"limit": None, "used": None, "resets_at": None},
                "last_error": {"code": latest["code"], "message": latest["message"][:300], "at": iso(latest["at"])}
                if latest
                else None,
            }
        )
    return {"connectors": out}


@router.get("/ops/jobs", operation_id="listJobs", summary="Durable jobs, filterable by status")
def list_jobs(
    _: Principal = Depends(require("listJobs")),
    db: Database[dict[str, Any]] = Depends(db_dep),
    job_status: str | None = Query(default=None),
    project_id: str | None = Query(default=None),
    cursor: str | None = Query(default=None),
    limit: int = Query(default=25, ge=1, le=100),
) -> dict[str, Any]:
    query: dict[str, Any] = {}
    if job_status:
        query["status"] = job_status
    if project_id:
        query["project_id"] = project_id
    before = decode_cursor(cursor)
    if before:
        query["_id"] = {"$lt": before}
    rows = list(db["ai_jobs"].find(query).sort("_id", -1).limit(limit + 1))
    more = len(rows) > limit
    rows = rows[:limit]
    return {
        "items": [job_view(r) for r in rows],
        "next_cursor": encode_cursor(rows[-1]["_id"]) if more and rows else None,
    }
