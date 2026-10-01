"""The video library for a project (Step 06.7; listMedia): each video or Short with its access state, transcript
route and timed segments. Discovery, transcript access and analysis stay separate fields (docs/06 media rules);
a video without an authorised transcript is listed like any other, with no segments."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query
from pymongo.database import Database

from app.api.deps import Principal, db_dep, known_id, require
from app.api.routes_ops import decode_cursor, encode_cursor
from app.api.routes_sources import LINK_RANK, source_view
from app.contracts import to_view
from app.errors import ApiError
from app.media.pipeline import VIDEO_KINDS

router = APIRouter(prefix="/v1", tags=["media"])
ACCESS = ("discovered", "access_pending", "metadata_only", "transcribed", "analysed", "error")
FORMATS = ("video", "short", "unknown")


@router.get("/projects/{project_id}/media", operation_id="listMedia", summary="Video and Short library")
def list_media(
    project_id: str,
    _: Principal = Depends(require("listMedia")),
    db: Database[dict[str, Any]] = Depends(db_dep),
    access_status: str | None = Query(default=None),
    format: str | None = Query(default=None),
    cursor: str | None = Query(default=None),
    limit: int = Query(default=25, ge=1, le=100),
) -> dict[str, Any]:
    known_id(project_id, "prj")
    if db["projects"].find_one({"_id": project_id}, {"_id": 1}) is None:
        raise ApiError(404, "not_found", "No such project")
    for name, value, allowed in (("access_status", access_status, ACCESS), ("format", format, FORMATS)):
        if value is not None and value not in allowed:
            raise ApiError(422, "validation_failed", f"{name} must be one of {', '.join(allowed)}")
    best: dict[str, str] = {}
    for link in db["ai_project_source_links"].find(
        {"project_id": project_id, "status": {"$ne": "superseded"}}, {"source": 1, "status": 1}
    ):
        key = f"{link['source']['id']}@{link['source']['revision']}"
        if LINK_RANK[link["status"]] > LINK_RANK.get(best.get(key, ""), 0):
            best[key] = link["status"]
    keys = sorted(best)
    before = decode_cursor(cursor)
    if before:
        keys = [k for k in keys if k < before]
    query: dict[str, Any] = {"_id": {"$in": keys}, "source_kind": {"$in": list(VIDEO_KINDS)}}
    if access_status is not None:
        query["media.access_status"] = access_status
    if format is not None:
        query["media.format"] = format
    rows = list(db["ai_sources"].find(query).sort("_id", -1).limit(limit + 1))
    more = len(rows) > limit
    rows = rows[:limit]
    items = []
    for video in rows:
        segments = (
            db["ai_media_segments"]
            .find({"source.id": video["id"], "source.revision": video["revision"]})
            .sort("time.start_ms", 1)
        )
        items.append(
            {
                "source": source_view(video),
                "link_status": best[video["_id"]],
                "segments": [to_view(seg) for seg in segments],
            }
        )
    return {"items": items, "next_cursor": encode_cursor(rows[-1]["_id"]) if more and rows else None}
