"""Moderator edits of findings and first-person reviews (Step 09.4; journeys J06, J07; D27, D28).

An edit always creates a new revision from the exact base revision the moderator saw; a newer revision makes it a
version conflict. The base becomes `superseded` (its decisions stay on record and the console labels them so), and
the new revision waits for review like any other. The backend keeps the evidence rules whatever the console sent:

- a finding cites exact claim revisions of its own project; its attribution must follow from those claims (an
  opinion cannot be relabelled a verified fact); every number in the wording must appear in a cited claim; the
  caveats the claims require (single source, disputed, contradicted, advertising) cannot be removed;
- a review shows spans of the same source revision only, every one still eligible; the shown words must be an
  honest rendering of the author's words (checked word by word unless translated); no dashes or hyphens, phone
  numbers or e-mail addresses; its construction-status flags are recomputed for the new spans.

Each edit is one transaction: the new revision, the base's status change at its expected status, and an audit event.
"""

from __future__ import annotations

from typing import Any

from pymongo import MongoClient
from pymongo.client_session import ClientSession
from pymongo.database import Database

from app import audit
from app.agents.common import numbers_in
from app.agents.consistency import consistency_flags
from app.agents.findings import _caveats, attribution_for
from app.agents.reviews import DASH, EMAIL, MAX_REVIEW_CHARS, PHONE, SPOKEN_KINDS, _position, rendering_problem
from app.contracts import ContractStore, to_view
from app.db import run_in_transaction, utcnow
from app.errors import ApiError
from app.evidence.clusters import independent_origins
from app.evidence.eligibility import eligibility
from app.evidence.retrieval import _translation_of


def _invalid(message: str, path: str) -> ApiError:
    return ApiError(422, "validation_failed", message, fields=[{"path": path, "message": message[:300]}])


def _base(
    db: Database[dict[str, Any]],
    contracts: ContractStore,
    collection: str,
    machine: str,
    base: dict[str, Any],
    actor: dict[str, Any],
    session: ClientSession,
) -> dict[str, Any]:
    latest = db[collection].find_one({"id": base["id"]}, sort=[("revision", -1)], session=session)
    if latest is None:
        raise ApiError(404, "not_found", "Not found")
    if latest["revision"] != base["revision"]:
        raise ApiError(
            409,
            "version_conflict",
            f"Revision {base['revision']} is not the latest; revision {latest['revision']} is",
            current_version=latest["revision"],
        )
    if not contracts.transition_allowed(machine, latest["review_status"], "superseded", actor["role"]):
        raise ApiError(409, "invalid_transition", f"A {latest['review_status']} revision cannot be edited")
    return latest


def _insert_and_supersede(
    db: Database[dict[str, Any]],
    collection: str,
    latest: dict[str, Any],
    doc: dict[str, Any],
    session: ClientSession,
) -> None:
    db[collection].insert_one(doc, session=session)
    changed = db[collection].update_one(
        {"_id": latest["_id"], "review_status": latest["review_status"]},
        {"$set": {"review_status": "superseded"}},
        session=session,
    )
    if changed.modified_count != 1:
        raise ApiError(409, "version_conflict", "The revision changed; reload it", current_version=latest["revision"])


def revise_finding(
    client: MongoClient[dict[str, Any]],
    db: Database[dict[str, Any]],
    contracts: ContractStore,
    finding_id: str,
    body: dict[str, Any],
    actor: dict[str, Any],
) -> dict[str, Any]:
    if body["base"]["id"] != finding_id:
        raise _invalid("The base names another finding", "base.id")

    def write(session: ClientSession) -> dict[str, Any]:
        latest = _base(db, contracts, "ai_findings", "finding_review", body["base"], actor, session)
        claims = []
        for ref in body["claims"]:
            claim = db["ai_claims"].find_one({"id": ref["id"], "revision": ref["revision"]}, session=session)
            if claim is None or claim["project_id"] != latest["project_id"]:
                raise _invalid(f"Claim {ref['id']} revision {ref['revision']} is not part of this project", "claims")
            claims.append(claim)
        support = [e for c in claims for e in c["supporting_evidence"]]
        origins = sorted(independent_origins(db, support))
        expected = attribution_for(claims, len(origins))
        if body["attribution"] != expected:
            raise _invalid(
                f"The cited claims support the attribution '{expected}', not '{body['attribution']}'", "attribution"
            )
        wording = " ".join(body["wording"].split())
        extra = numbers_in(wording) - numbers_in(" ".join(c["statement"] for c in claims))
        if extra:
            raise _invalid(f"Numbers not in any cited claim: {', '.join(sorted(extra))}", "wording")
        caveats = [" ".join(c.split()) for c in body["caveats"] if c.strip()]
        missing = [c for c in _caveats([], claims, expected, len(origins)) if c not in caveats]
        if missing:
            raise _invalid("These caveats are required by the cited claims: " + "; ".join(missing), "caveats")
        revision = latest["revision"] + 1
        doc = {
            "_id": f"{finding_id}@{revision}",
            "id": finding_id,
            "revision": revision,
            "project_id": latest["project_id"],
            "kind": body["kind"],
            "aspect": body["aspect"],
            "wording": wording,
            "attribution": expected,
            "claims": [{"id": c["id"], "revision": c["revision"]} for c in claims],
            "caveats": list(dict.fromkeys(caveats)),
            "origin_clusters": origins,
            "independent_origin_count": len(origins),
            "review_status": "pending",
            "supersedes": {"id": finding_id, "revision": latest["revision"]},
            "created_by": {"kind": "moderator", "task_id": None, "actor": actor},
            "created_at": utcnow(),
        }
        problems = contracts.errors(to_view(doc, id_field=None) or {}, "evidence.schema.json#/$defs/Finding")
        if problems:
            raise _invalid("; ".join(problems[:3]), "body")
        _insert_and_supersede(db, "ai_findings", latest, doc, session)
        audit.record(
            db,
            "finding.revised",
            "finding",
            finding_id,
            actor,
            revision=revision,
            details={"base": latest["revision"], "reason": body["reason"][:300]},
            session=session,
        )
        return doc

    doc = run_in_transaction(client, write)
    view = to_view(doc, id_field=None)
    assert view is not None
    return view


def revise_review(
    client: MongoClient[dict[str, Any]],
    db: Database[dict[str, Any]],
    contracts: ContractStore,
    excerpt_id: str,
    body: dict[str, Any],
    actor: dict[str, Any],
) -> dict[str, Any]:
    if body["base"]["id"] != excerpt_id:
        raise _invalid("The base names another review", "base.id")

    def write(session: ClientSession) -> dict[str, Any]:
        latest = _base(db, contracts, "ai_review_excerpts", "review_excerpt", body["base"], actor, session)
        spans = []
        for ref in body["evidence"]:
            span = db["ai_evidence"].find_one({"id": ref["id"], "revision": ref["revision"]}, session=session)
            if span is None or span["source"] != latest["source"] or span["project_id"] != latest["project_id"]:
                raise _invalid("Every span must come from the review's own source revision", "evidence")
            if span.get("excerpt_text") is None or not eligibility(db, span, session=session).eligible:
                raise _invalid(f"Span {ref['id']} is no longer eligible", "evidence")
            spans.append(span)
        if len({(s["id"], s["revision"]) for s in spans}) != len(spans):
            raise _invalid("A span is listed twice", "evidence")
        spans.sort(key=_position)
        text = body["text"].strip()
        original = "\n".join(s["excerpt_text"] for s in spans)
        translations = " ".join(t for t in (_translation_of(db, s) for s in spans) if t)
        problem = rendering_problem(body["rendering"], text, original, [s["language"] for s in spans], translations)
        if problem:
            raise _invalid(f"The text is not a {body['rendering']} rendering of the author's words ({problem})", "text")
        if DASH.search(text):
            raise _invalid("Displayed reviews have no dashes or hyphens", "text")
        if PHONE.search(text) or EMAIL.search(text):
            raise _invalid("The text contains a phone number or e-mail address", "text")
        if len(text) > MAX_REVIEW_CHARS:
            raise _invalid(f"A review shows at most {MAX_REVIEW_CHARS} characters", "text")
        config = db["ai_project_configs"].find_one({"_id": latest["project_id"]}, session=session) or {}
        link = db["ai_project_source_links"].find_one({"_id": spans[0]["link_id"]}, {"phase": 1}, session=session)
        flags = consistency_flags(
            latest["perspective"],
            config.get("construction_status") or [],
            ((link or {}).get("phase") or {}).get("rera_id"),
            latest["published"].get("value"),
            aspects=latest["aspects"],
            polarity=latest["polarity"],
        )
        revision = latest["revision"] + 1
        doc = {
            **{k: v for k, v in latest.items() if k not in ("_id", "created_at")},
            "_id": f"{excerpt_id}@{revision}",
            "revision": revision,
            "link_id": spans[0]["link_id"],
            "evidence": [{"id": s["id"], "revision": s["revision"]} for s in spans],
            "original_text": original,
            "original_language": spans[0]["language"],
            "rendering": body["rendering"],
            "text": text,
            "timestamp_ms": spans[0]["anchor"].get("start_ms") if latest["source_kind"] in SPOKEN_KINDS else None,
            "consistency_flags": flags,
            "policy": spans[0]["policy"],
            "review_status": "pending",
            "supersedes": {"id": excerpt_id, "revision": latest["revision"]},
            "created_by": {"kind": "moderator", "task_id": None, "actor": actor},
            "lifecycle": "active",
            "created_at": utcnow(),
        }
        problems = contracts.errors(to_view(doc, id_field=None) or {}, "evidence.schema.json#/$defs/ReviewExcerpt")
        if problems:
            raise _invalid("; ".join(problems[:3]), "body")
        _insert_and_supersede(db, "ai_review_excerpts", latest, doc, session)
        audit.record(
            db,
            "review.revised",
            "review_excerpt",
            excerpt_id,
            actor,
            revision=revision,
            details={"base": latest["revision"], "reason": body["reason"][:300], "rendering": body["rendering"]},
            session=session,
        )
        return doc

    doc = run_in_transaction(client, write)
    view = to_view(doc, id_field=None)
    assert view is not None
    return view
