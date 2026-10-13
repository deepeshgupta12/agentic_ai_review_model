"""Sources for a project, one source revision in detail, and withdrawal (Step 05; journeys J03, J12)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Body, Depends, Header, Query
from pymongo.database import Database

from app.api.deps import Principal, contract_body, contracts_dep, db_dep, known_id, require
from app.api.idempotency import HEADER, run_idempotent
from app.api.routes_ops import decode_cursor, encode_cursor
from app.contracts import ContractStore, to_view
from app.errors import ApiError
from app.evidence.eligibility import eligibility
from app.identity.intake import source_text
from app.identity.links import link_view
from app.identity.text import sha256_text
from app.sources.lifecycle import withdraw

router = APIRouter(prefix="/v1", tags=["sources"])
LINK_RANK = {"accepted": 4, "auto_accepted": 3, "needs_review": 2, "rejected": 1}


def source_view(doc: dict[str, Any]) -> dict[str, Any]:
    view = to_view(doc, id_field=None)
    assert view is not None
    return view


def utf16(text: str, index: int) -> int:
    return sum(2 if ord(ch) > 0xFFFF else 1 for ch in text[:index])


def evidence_view(
    db: Database[dict[str, Any]], evidence: dict[str, Any], source: dict[str, Any], text: str | None
) -> dict[str, Any]:
    """Evidence with UTF-16 offsets for browsers and whether findings may use it now (D24, D50)."""
    reasons = eligibility(db, evidence).reasons
    anchor = dict(evidence["anchor"])
    if anchor.get("kind") == "text":
        basis = text if text is not None else (evidence.get("excerpt_text") or "")
        start = anchor["start"] if text is not None else 0
        end = anchor["end"] if text is not None else len(basis)
        anchor["utf16_start"] = utf16(basis, start)
        anchor["utf16_end"] = utf16(basis, end)
    view = to_view({k: v for k, v in evidence.items() if k != "_id"}, id_field=None)
    assert view is not None
    return {"evidence": view, "anchor_view": anchor, "eligible": not reasons, "ineligibility_reasons": reasons}


def aspects_by_source(db: Database[dict[str, Any]], project_id: str) -> dict[str, set[str]]:
    """Source revision -> the aspects of the project's claims that its evidence supports (Step 08)."""
    source_of = {
        e["id"]: f"{e['source']['id']}@{e['source']['revision']}"
        for e in db["ai_evidence"].find({"project_id": project_id}, {"id": 1, "source": 1})
    }
    found: dict[str, set[str]] = {}
    for claim in db["ai_claims"].find({"project_id": project_id}, {"aspect": 1, "supporting_evidence.id": 1}):
        for ref in claim["supporting_evidence"]:
            if ref["id"] in source_of:
                found.setdefault(source_of[ref["id"]], set()).add(claim["aspect"])
    return found


@router.get("/projects/{project_id}/sources", operation_id="listSources", summary="Sources linked to a project")
def list_sources(
    project_id: str,
    _: Principal = Depends(require("listSources")),
    db: Database[dict[str, Any]] = Depends(db_dep),
    connector_id: str | None = Query(default=None),
    source_kind: str | None = Query(default=None),
    aspect: str | None = Query(default=None),
    language: str | None = Query(default=None),
    published_from: str | None = Query(default=None),
    published_to: str | None = Query(default=None),
    cursor: str | None = Query(default=None),
    limit: int = Query(default=25, ge=1, le=100),
) -> dict[str, Any]:
    known_id(project_id, "prj")
    if db["projects"].find_one({"_id": project_id}, {"_id": 1}) is None:
        raise ApiError(404, "not_found", "No such project")
    best: dict[str, str] = {}
    for link in db["ai_project_source_links"].find(
        {"project_id": project_id, "status": {"$ne": "superseded"}}, {"source": 1, "status": 1}
    ):
        key = f"{link['source']['id']}@{link['source']['revision']}"
        if LINK_RANK[link["status"]] > LINK_RANK.get(best.get(key, ""), 0):
            best[key] = link["status"]
    aspects = aspects_by_source(db, project_id)
    if aspect is not None:
        best = {k: v for k, v in best.items() if aspect in aspects.get(k, set())}
    query: dict[str, Any] = {"_id": {"$in": sorted(best)}}
    for field, value in (("connector_id", connector_id), ("source_kind", source_kind), ("language", language)):
        if value is not None:
            query[field] = value
    dates: dict[str, Any] = {}
    for bound, value, op in (("from", published_from, "$gte"), ("to", published_to, "$lte")):
        if value is not None:
            try:
                day = datetime.fromisoformat(value).replace(tzinfo=UTC)
            except ValueError as exc:
                raise ApiError(422, "validation_failed", f"published_{bound} is not a date") from exc
            dates[op] = day if bound == "from" else day.replace(hour=23, minute=59, second=59)
    if dates:
        query["publication_date.value"] = dates
    before = decode_cursor(cursor)
    if before:
        query["_id"] = {"$in": sorted(k for k in best if k < before)}
    rows = list(db["ai_sources"].find(query).sort("_id", -1).limit(limit + 1))
    more = len(rows) > limit
    rows = rows[:limit]
    items = [
        {
            "source": {"id": s["id"], "revision": s["revision"]},
            "connector_id": s["connector_id"],
            "source_kind": s["source_kind"],
            "title": s["title"],
            "canonical_url": s["canonical_url"],
            "publication_date": s["publication_date"],
            "language": s["language"],
            "capture_level": s["capture_level"],
            "lifecycle": s["lifecycle"],
            "link_status": best[s["_id"]],
            "aspects": sorted(aspects.get(s["_id"], set())),
        }
        for s in rows
    ]
    return {"items": items, "next_cursor": encode_cursor(rows[-1]["_id"]) if more and rows else None}


@router.get(
    "/sources/{source_id}/revisions/{revision}",
    operation_id="getSourceRevision",
    summary="One source revision with its permitted text, links and evidence",
)
def get_source_revision(
    source_id: str,
    revision: int,
    _: Principal = Depends(require("getSourceRevision")),
    db: Database[dict[str, Any]] = Depends(db_dep),
) -> dict[str, Any]:
    known_id(source_id, "src")
    source = db["ai_sources"].find_one({"id": source_id, "revision": revision})
    if source is None:
        raise ApiError(404, "not_found", "No such source revision")
    text = source_text(db, source)
    permitted = text if text is not None and source["lifecycle"] in ("active", "stale", "unavailable") else None
    if permitted is not None and source["content_sha256"] != sha256_text(permitted):
        permitted = None  # never show text that no longer matches its recorded hash
    links = list(db["ai_project_source_links"].find({"source.id": source_id, "source.revision": revision}))
    evidence = list(db["ai_evidence"].find({"source.id": source_id, "source.revision": revision}))
    return {
        "source": source_view(source),
        "permitted_text": permitted,
        "links": [link_view(lk) for lk in links],
        "evidence": [evidence_view(db, e, source, permitted) for e in evidence],
    }


@router.post(
    "/sources/{source_id}/withdrawals",
    operation_id="withdrawSource",
    summary="Withdraw a source revision or all its revisions",
    status_code=202,
)
def withdraw_source(
    source_id: str,
    body: Any = Body(...),
    idempotency_key: str | None = Header(default=None, alias=HEADER),
    principal: Principal = Depends(require("withdrawSource")),
    db: Database[dict[str, Any]] = Depends(db_dep),
    contracts: ContractStore = Depends(contracts_dep),
) -> dict[str, Any]:
    known_id(source_id, "src")
    request = contract_body(contracts, body, "api.schema.json#/$defs/WithdrawalRequest")
    return run_idempotent(
        db,
        operation_id=f"withdrawSource:{source_id}",
        user_id=principal.user_id,
        key=idempotency_key,
        body=request,
        compute=lambda: withdraw(db.client, db, contracts, source_id, request, principal.actor),
    )
