"""Content revisions: generation, moderator edits, final approval and decisions (Step 10; docs/05 "Immutable content
and hashing"; state machines `content_lifecycle` and `workflow_stage`; D23, D64, D66).

- A revision's payload and manifest are frozen and hashed (JCS, SHA-256); lifecycle and QA counts are metadata
  outside the hash. A changed word, link, date or metadata value is a new revision.
- Generation (the analysis graph's `format` node, after a moderator's selection): approved review revisions as
  approved, plus A08 blocks when findings were selected; deterministic QA, then A09 on model-written text. Without a
  blocking issue the revision goes to final review; otherwise it stays a draft for the moderator to edit.
- Edits: the moderator sends the whole payload; the backend keeps only what an editor may change (heading, blocks,
  coverage note, metadata title and description, which approved reviews to show and in which order), rebuilds the
  rest (credits, sources, manifest, JSON-LD, dates) and runs the same checks. Blocks may cite only the findings of the
  base revision; a review is always the approved record (D28) and may be any approved review of the project (D69),
  within the page's review limits.
- Final approval binds the exact revision, recomputed payload and manifest hashes, the eligibility epoch and the
  publication state version (ContentBinding). Every finding and review is checked again; the actor is the signed-in
  moderator. An approval of one hash can never authorise another revision.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, date, datetime
from typing import Any

from pymongo import ReturnDocument
from pymongo.client_session import ClientSession
from pymongo.database import Database
from pymongo.errors import DuplicateKeyError

from app import audit
from app.agents.common import stable_id
from app.agents.consistency import status_in_force
from app.agents.gateway import ModelGateway
from app.config import Settings
from app.content import build, editor
from app.content.hashing import CanonicalError, content_hash, nfc
from app.content.qa import Basis, check_payload, issue, summary
from app.contracts import ContractStore, to_view
from app.db import run_in_transaction, utcnow
from app.decisions import record_decision
from app.errors import ApiError
from app.workflows.decisions import finding_problems, review_problems

REVISIONS, QA, STATES = "ai_content_revisions", "ai_content_qa", "ai_publication_state"
# A model error that must stop or retry the job rather than become a draft with a blocking issue (as in analysis).
UNAVAILABLE = {
    "budget_exhausted",
    "access_pending",
    "no_spend_ledger",
    "price_unknown",
    "model_not_found",
    "provider_unavailable",
}


class ModelUnavailable(Exception):
    def __init__(self, error: dict[str, str]) -> None:
        super().__init__(f"{error['code']}: {error['message']}")
        self.error = error


# A withdrawn revision (its evidence was withdrawn) is the way back: an edit rebuilds the page from the reviews and
# findings approved now, without the withdrawn ones, and needs a new final approval (audit, 14 Oct 2026).
EDITABLE_BASE = {"draft", "final_review", "changes_requested", "approved", "rejected", "withdrawn"}
LOCALE = build.LOCALE


# --- publication control document -----------------------------------------------------------------------------------


def state_id(project_id: str, locale: str = LOCALE) -> str:
    return f"{project_id}:{locale}"


def publication_state(
    db: Database[dict[str, Any]], project_id: str, locale: str = LOCALE, session: ClientSession | None = None
) -> dict[str, Any]:
    """The project/locale control document (docs/05), created unpublished at version 0 the first time it is needed."""
    now = utcnow()
    doc = db[STATES].find_one_and_update(
        {"_id": state_id(project_id, locale)},
        {
            "$setOnInsert": {
                "project_id": project_id,
                "locale": locale,
                "version": 0,
                "approved": None,
                "active": None,
                "serving_state": "unpublished",
                "eligibility_epoch": 0,
                "pending_invalidation": False,
                "pending_intent": None,
                "updated_at": now,
            }
        },
        upsert=True,
        return_document=ReturnDocument.AFTER,
        session=session,
    )
    assert doc is not None
    return dict(doc)


# --- views ----------------------------------------------------------------------------------------------------------


def revision_record(doc: dict[str, Any]) -> dict[str, Any]:
    view = to_view(doc)
    assert view is not None
    return view


def revision_view(db: Database[dict[str, Any]], doc: dict[str, Any]) -> dict[str, Any]:
    state = db[STATES].find_one({"_id": state_id(doc["project_id"], doc["locale"])}) or {}
    qa = db[QA].find_one({"_id": doc["_id"]}) or {}
    return {
        "revision": revision_record(doc),
        "preview_path": f"/console/projects/{doc['project_id']}/content/{doc['_id']}/preview",
        "is_approved": (state.get("approved") or {}).get("revision_id") == doc["_id"],
        "is_active": (state.get("active") or {}).get("revision_id") == doc["_id"],
        "qa_issues": qa.get("issues", []),
    }


# --- shared building ------------------------------------------------------------------------------------------------


def _today() -> date:
    return datetime.now(UTC).date()


def _exact(
    db: Database[dict[str, Any]], collection: str, refs: list[dict[str, Any]], session: ClientSession | None
) -> list[dict[str, Any]]:
    out = []
    for ref in refs:
        doc = db[collection].find_one({"id": ref["id"], "revision": ref["revision"]}, session=session)
        if doc is None:
            raise ApiError(409, "ineligible_dependency", f"{ref['id']} revision {ref['revision']} is missing")
        out.append(doc)
    return out


def check_review_limits(db: Database[dict[str, Any]], settings: Settings, refs: list[dict[str, Any]]) -> None:
    """The published review list (D69): at most `page_reviews_max` reviews, each `review_words_min` to
    `review_words_max` words as approved. Checked on generation and on every edit."""
    out_of_range = []
    for ref in refs:
        review = db["ai_review_excerpts"].find_one({"id": ref["id"], "revision": ref["revision"]}, {"text": 1})
        count = len(((review or {}).get("text") or "").split())
        if not settings.review_words_min <= count <= settings.review_words_max:
            out_of_range.append(f"{ref['id']} ({count} words)")
    if out_of_range:
        raise ApiError(
            422,
            "validation_failed",
            f"Published reviews have {settings.review_words_min} to {settings.review_words_max} words (D69)",
            fields=[{"path": "reviews", "message": "; ".join(out_of_range)[:300]}],
        )
    if len(refs) > settings.page_reviews_max:
        raise ApiError(
            422,
            "validation_failed",
            f"A page shows at most {settings.page_reviews_max} reviews (D69); select fewer",
            fields=[{"path": "reviews", "message": f"{len(refs)} selected"}],
        )


def _left_out(
    db: Database[dict[str, Any]], project_id: str, findings: list[dict[str, Any]], reviews: list[dict[str, Any]]
) -> dict[str, int]:
    """Approved, current findings and reviews of each side that the page does not use (balance notes)."""
    chosen = {f["id"] for f in findings} | {r["id"] for r in reviews}
    out: dict[str, int] = {}
    for doc in db["ai_findings"].find({"project_id": project_id, "review_status": "approved"}, {"id": 1, "kind": 1}):
        if doc["id"] not in chosen and doc["kind"] in ("pro", "con"):
            out[doc["kind"]] = out.get(doc["kind"], 0) + 1
    for doc in db["ai_review_excerpts"].find(
        {"project_id": project_id, "review_status": "approved"}, {"id": 1, "polarity": 1}
    ):
        if doc["id"] not in chosen:
            out[doc["polarity"]] = out.get(doc["polarity"], 0) + 1
    return out


def _basis(
    db: Database[dict[str, Any]],
    project: dict[str, Any],
    config: dict[str, Any],
    findings: list[dict[str, Any]],
    reviews: list[dict[str, Any]],
    session: ClientSession | None,
) -> tuple[Basis, dict[tuple[str, int], dict[str, Any]], list[dict[str, Any]]]:
    claims = {(c["id"], c["revision"]): c for c in build.claims_of(db, findings, session)}
    public = [build.public_review(db, r, session) for r in reviews]
    basis = Basis(
        project=project,
        findings={(f["id"], f["revision"]): f for f in findings},
        claims=claims,
        reviews={(r["id"], r["revision"]): nfc(p) for r, p in zip(reviews, public, strict=True)},
        status=status_in_force(config.get("construction_status") or [], None, _today()),
        left_out=_left_out(db, project["_id"], findings, reviews),
    )
    return basis, claims, public


def _assemble(
    db: Database[dict[str, Any]],
    settings: Settings,
    contracts: ContractStore,
    project: dict[str, Any],
    findings: list[dict[str, Any]],
    reviews: list[dict[str, Any]],
    public: list[dict[str, Any]],
    claims: dict[tuple[str, int], dict[str, Any]],
    blocks: dict[str, Any],
    metadata: dict[str, str] | None,
    epoch: int,
    session: ClientSession | None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    manifest = build.manifest_for(db, findings, reviews, epoch, session)
    today = _today()
    payload = build.assemble(
        project=project,
        settings=settings,
        reviews=reviews,
        public_reviews=public,
        findings_count=len(findings),
        blocks=blocks,
        sources=build.source_links(db, list(claims.values()), session) if findings else [],
        window=build.evidence_window(db, manifest, today, session),
        today=today,
        metadata=metadata,
    )
    problems = contracts.errors(payload, "content.schema.json#/$defs/ContentPayload")
    problems += contracts.errors(manifest, "content.schema.json#/$defs/DependencyManifest")
    if problems:
        raise ApiError(
            422,
            "validation_failed",
            "The page content does not meet the contract",
            fields=[{"path": p.split(": ", 1)[0], "message": p.split(": ", 1)[-1][:300]} for p in problems[:10]],
        )
    return payload, manifest


def _next_revision(db: Database[dict[str, Any]], project_id: str, locale: str, session: ClientSession | None) -> int:
    latest = db[REVISIONS].find_one(
        {"project_id": project_id, "locale": locale}, sort=[("revision", -1)], session=session
    )
    return (latest["revision"] + 1) if latest else 1


def _supersede_open(
    db: Database[dict[str, Any]],
    contracts: ContractStore,
    project_id: str,
    locale: str,
    keep: str,
    role: str,
    session: ClientSession,
) -> None:
    """Older unapproved revisions give way to the new one (approved ones stay until a newer one is approved)."""
    for doc in db[REVISIONS].find(
        {
            "project_id": project_id,
            "locale": locale,
            "_id": {"$ne": keep},
            "lifecycle": {"$in": ["draft", "final_review", "changes_requested"]},
        },
        {"lifecycle": 1, "revision": 1},
        session=session,
    ):
        if contracts.transition_allowed("content_lifecycle", doc["lifecycle"], "superseded", role):
            db[REVISIONS].update_one(
                {"_id": doc["_id"], "lifecycle": doc["lifecycle"]},
                {"$set": {"lifecycle": "superseded"}},
                session=session,
            )


def _store(
    db: Database[dict[str, Any]],
    contracts: ContractStore,
    doc: dict[str, Any],
    issues: list[dict[str, Any]],
    role: str,
    session: ClientSession,
) -> None:
    problems = contracts.errors(revision_record(doc), "content.schema.json#/$defs/ContentRevision")
    if problems:
        raise ApiError(422, "validation_failed", "The revision does not meet the contract: " + "; ".join(problems[:3]))
    db[REVISIONS].insert_one(doc, session=session)
    db[QA].insert_one({"_id": doc["_id"], "issues": issues, "created_at": doc["created_at"]}, session=session)
    _supersede_open(db, contracts, doc["project_id"], doc["locale"], doc["_id"], role, session)


# --- generation (analysis graph `format` node) ----------------------------------------------------------------------


def generate(
    db: Database[dict[str, Any]],
    contracts: ContractStore,
    settings: Settings,
    gateway: ModelGateway,
    *,
    run: dict[str, Any],
    selection: dict[str, Any],
) -> dict[str, Any]:
    """Build, check and store the content revision for a moderator's selection. Idempotent per run and selection: a
    node that runs again after a crash finds the revision it stored (model outputs are cached per task).
    Returns {revision_id, lifecycle, qa, model_error}."""
    project_id = run["project_id"]
    locale = selection.get("locale") or LOCALE
    digest = hashlib.sha256(
        json.dumps([selection["findings"], selection["reviews"], locale], sort_keys=True).encode()
    ).hexdigest()
    revision_id = stable_id("rev", run["_id"], "generate", digest)
    existing = db[REVISIONS].find_one({"_id": revision_id})
    if existing is not None:
        return {
            "revision_id": revision_id,
            "lifecycle": existing["lifecycle"],
            "qa": existing["qa"],
            "model_error": None,
        }
    project = db["projects"].find_one({"_id": project_id})
    config = db["ai_project_configs"].find_one({"_id": project_id})
    if project is None or config is None:
        raise LookupError("the project or its configuration is missing")
    findings = _exact(db, "ai_findings", selection["findings"], None)
    # one balanced list (D69): positive, negative and mixed alternate in proportion, at most PAGE_REVIEWS_MAX
    reviews = build.balanced(_exact(db, "ai_review_excerpts", selection["reviews"], None), settings.page_reviews_max)
    basis, claims, public = _basis(db, project, config, findings, reviews, None)
    blocks: dict[str, Any] = {"overview": None}
    metadata = None
    task_id = None
    model_error = None
    extra_issues: list[dict[str, Any]] = []
    if findings:
        written = editor.write_draft(
            db,
            gateway,
            project=project,
            status=basis.status,
            findings=findings,
            claims=claims,
            review_count=len(reviews),
            run_id=run["_id"],
        )
        task_id = written["task_id"]
        # a cut-off or invalid draft is not stored as an empty page: the page building stops and can be continued
        if written["outcome"] == "failed" and written["error"]["code"] in UNAVAILABLE | {
            "incomplete",
            "invalid_output",
        }:
            raise ModelUnavailable(written["error"])
        if written["outcome"] == "failed":
            model_error = written["error"]
            extra_issues.append(
                issue(
                    "overview",
                    None,
                    "blocking",
                    "other",
                    f"the editor could not write the findings blocks ({model_error['code']})",
                )
            )
        else:
            blocks, metadata = written["blocks"], written["metadata"]
    epoch = publication_state(db, project_id, locale)["eligibility_epoch"]
    payload, manifest = _assemble(
        db, settings, contracts, project, findings, reviews, public, claims, blocks, metadata, epoch, None
    )
    payload_sha = content_hash(payload)
    issues = check_payload(payload, basis) + extra_issues
    report_task = None
    if findings and model_error is None:
        checked = editor.check_draft(
            db,
            gateway,
            project_id=project_id,
            payload_sha256=payload_sha,
            payload=payload,
            findings=basis.findings,
            claims=claims,
            reviews=reviews,
            run_id=run["_id"],
        )
        report_task = checked["task_id"]
        if checked["outcome"] == "failed" and checked["error"]["code"] in UNAVAILABLE:
            raise ModelUnavailable(checked["error"])
        if checked["outcome"] == "failed":
            model_error = checked["error"]
            issues.append(
                issue("overview", None, "blocking", "other", f"editorial QA could not run ({model_error['code']})")
            )
        else:
            issues += checked["issues"]
    qa = summary(issues, report_task)
    lifecycle = "final_review" if qa["blocking_issues"] == 0 else "draft"
    actor = selection.get("actor") or audit.SYSTEM_ACTOR

    def write(session: ClientSession) -> None:
        if db[REVISIONS].find_one({"_id": revision_id}, {"_id": 1}, session=session):
            return
        doc = {
            "_id": revision_id,
            "project_id": project_id,
            "locale": locale,
            "revision": _next_revision(db, project_id, locale, session),
            "payload": payload,
            "payload_sha256": payload_sha,
            "manifest": manifest,
            "manifest_sha256": content_hash(manifest),
            "lifecycle": lifecycle,
            "supersedes": None,
            "created_by": {"kind": "agent", "task_id": task_id, "actor": None},
            "qa": qa,
            "created_at": utcnow(),
        }
        _store(db, contracts, doc, issues, actor.get("role") or "system", session)
        db["ai_runs"].update_one({"_id": run["_id"]}, {"$set": {"content_revision_id": revision_id}}, session=session)
        audit.record(
            db,
            "content.generated",
            "content_revision",
            revision_id,
            audit.SYSTEM_ACTOR,
            revision=doc["revision"],
            details={
                "findings": len(findings),
                "reviews": len(reviews),
                "lifecycle": lifecycle,
                "blocking_issues": qa["blocking_issues"],
            },
            session=session,
        )

    try:
        run_in_transaction(db.client, write)
    except DuplicateKeyError:  # a concurrent writer took the revision number; the stored one wins
        pass
    stored = db[REVISIONS].find_one({"_id": revision_id}) or {}
    return {
        "revision_id": revision_id,
        "lifecycle": stored.get("lifecycle"),
        "qa": stored.get("qa"),
        "model_error": model_error,
    }


# --- moderator edit -------------------------------------------------------------------------------------------------


def _latest(db: Database[dict[str, Any]], project_id: str, locale: str, session: ClientSession | None) -> Any:
    return db[REVISIONS].find_one(
        {"project_id": project_id, "locale": locale}, sort=[("revision", -1)], session=session
    )


def _move_run(
    db: Database[dict[str, Any]],
    contracts: ContractStore,
    project_id: str,
    to: str,
    role: str,
    note: str,
    actor: dict[str, Any] | None = None,
) -> None:
    from app.workflows.analysis import move_stage  # the graph imports this module; import late

    run = db["ai_runs"].find_one(
        # the run that holds the page now: never a cancelled or published one (audit, 14 Oct 2026)
        {
            "project_id": project_id,
            "content_revision_id": {"$ne": None},
            "stage": {"$nin": ["published", "insufficient_evidence", "cancelled"]},
        },
        sort=[("created_at", -1)],
    )
    if run is None or run["stage"] == to or not contracts.transition_allowed("workflow_stage", run["stage"], to, role):
        return
    move_stage(contracts, db, run["_id"], run["stage"], to, role, note, None, actor)


def save_edit(
    db: Database[dict[str, Any]],
    contracts: ContractStore,
    settings: Settings,
    project_id: str,
    body: dict[str, Any],
    actor: dict[str, Any],
) -> dict[str, Any]:
    locale = body["locale"]
    base = db[REVISIONS].find_one({"_id": body["base"]["id"]})
    if base is None or base["project_id"] != project_id or base["locale"] != locale:
        raise ApiError(404, "not_found", "Not found")
    latest = _latest(db, project_id, locale, None)
    if base["revision"] != body["base"]["revision"] or latest["_id"] != base["_id"]:
        raise ApiError(
            409,
            "version_conflict",
            f"Revision {body['base']['revision']} is not the latest; revision {latest['revision']} is",
            current_version=latest["revision"],
        )
    if base["lifecycle"] not in EDITABLE_BASE:
        raise ApiError(409, "invalid_transition", f"A {base['lifecycle']} revision cannot be edited")
    edited = nfc(body["payload"])
    allowed = {(f["id"], f["revision"]) for f in base["manifest"]["findings"]}
    cited = []
    for block in ("advantages", "considerations", "questions"):
        cited += [r for item in edited[block] for r in item["support"]["findings"]]
    if edited["overview"] is not None:
        cited += edited["overview"]["support"]["findings"]
    if any((r["id"], r["revision"]) not in allowed for r in cited):
        raise ApiError(
            422,
            "validation_failed",
            "Blocks may cite only the findings of the base revision; generate again to add others",
        )
    base_reviews = {(r["id"], r["revision"]) for r in base["manifest"]["reviews"]}
    shown = [(r["support"]["review"]["id"], r["support"]["review"]["revision"]) for r in edited["reviews"]]
    if len(set(shown)) != len(shown):
        raise ApiError(422, "validation_failed", "Each review can be shown once")
    if not shown and not cited:  # an edit may not empty the page (generation refuses an empty selection too)
        raise ApiError(422, "validation_failed", "The page needs at least one review or finding")
    # D69: an edit may also add another approved review of this project (its words as approved; no model is involved).
    # It must be the latest, approved and approvable revision; the new revision needs its own final approval.
    added = [{"id": i, "revision": r} for i, r in shown if (i, r) not in base_reviews]
    problems = dependency_problems(db, {"findings": [], "reviews": added})
    if problems:
        raise ApiError(409, "ineligible_dependency", "Cannot show: " + "; ".join(problems))
    check_review_limits(db, settings, [{"id": i, "revision": r} for i, r in shown])
    project = db["projects"].find_one({"_id": project_id})
    config = db["ai_project_configs"].find_one({"_id": project_id})
    assert project is not None and config is not None
    findings = _exact(
        db,
        "ai_findings",
        [{"id": i, "revision": r} for i, r in sorted({(r["id"], r["revision"]) for r in cited})],
        None,
    )
    reviews = _exact(db, "ai_review_excerpts", [{"id": i, "revision": r} for i, r in shown], None)
    if any(r["project_id"] != project_id for r in reviews):
        raise ApiError(422, "validation_failed", "A review of another project cannot be shown")
    basis, claims, public = _basis(db, project, config, findings, reviews, None)
    blocks = {
        k: edited[k] for k in ("heading", "overview", "advantages", "considerations", "questions", "coverage_note")
    }
    metadata = {k: edited["metadata"][k] for k in ("title", "description")}
    # Text the backend wrote from the counts (coverage note, search title and description) follows the reviews now
    # shown; text the moderator wrote is kept as written, and QA checks its numbers.
    base_findings = len(base["manifest"]["findings"])
    if blocks["coverage_note"] == build.default_coverage_note([], base["payload"]["reviews"], base_findings):
        blocks["coverage_note"] = None
    was = build.default_metadata(project, len(base["manifest"]["reviews"]), base_findings)
    now = build.default_metadata(project, len(reviews), len(findings))
    metadata = {k: now[k] if metadata[k] == was[k] else metadata[k] for k in metadata}
    epoch = publication_state(db, project_id, locale)["eligibility_epoch"]
    payload, manifest = _assemble(
        db, settings, contracts, project, findings, reviews, public, claims, blocks, metadata, epoch, None
    )
    try:
        payload_sha = content_hash(payload)
    except CanonicalError as exc:
        raise ApiError(422, "validation_failed", str(exc)) from exc
    if payload_sha == base["payload_sha256"] and content_hash(manifest) == base["manifest_sha256"]:
        raise ApiError(422, "validation_failed", "Nothing changed: the payload is identical to the base revision")
    issues = check_payload(payload, basis)
    qa = summary(issues, None)
    lifecycle = "final_review" if qa["blocking_issues"] == 0 else "draft"

    def write(session: ClientSession) -> dict[str, Any]:
        current = _latest(db, project_id, locale, session)
        if current["_id"] != base["_id"]:
            raise ApiError(
                409, "version_conflict", "A newer revision was saved; reload it", current_version=current["revision"]
            )
        doc = {
            "_id": stable_id("rev", project_id, locale, str(base["revision"] + 1), payload_sha),
            "project_id": project_id,
            "locale": locale,
            "revision": base["revision"] + 1,
            "payload": payload,
            "payload_sha256": payload_sha,
            "manifest": manifest,
            "manifest_sha256": content_hash(manifest),
            "lifecycle": lifecycle,
            "supersedes": {"id": base["_id"], "revision": base["revision"]},
            "created_by": {"kind": "moderator", "task_id": None, "actor": actor},
            "qa": qa,
            "created_at": utcnow(),
        }
        _store(db, contracts, doc, issues, actor["role"], session)
        audit.record(
            db,
            "content.edited",
            "content_revision",
            doc["_id"],
            actor,
            revision=doc["revision"],
            details={"base": base["revision"], "reason": body["reason"][:300], "lifecycle": lifecycle},
            session=session,
        )
        return doc

    try:
        doc = run_in_transaction(db.client, write)
    except DuplicateKeyError as exc:
        raise ApiError(409, "version_conflict", "Another editor saved this revision number first; reload it") from exc
    if lifecycle == "draft":
        _move_run(
            db,
            contracts,
            project_id,
            "formatting",
            "moderator",
            f"Edited as revision {doc['revision']}; QA found blocking issues",
            actor,
        )
    else:
        _move_run(db, contracts, project_id, "formatting", "moderator", f"Edited as revision {doc['revision']}", actor)
        _move_run(db, contracts, project_id, "final_review", "system", f"Revision {doc['revision']} passed QA")
    return revision_view(db, doc)


# --- final approval and decisions -----------------------------------------------------------------------------------


def dependency_problems(
    db: Database[dict[str, Any]], manifest: dict[str, Any], session: ClientSession | None = None
) -> list[str]:
    """Each finding and review of the manifest is still the latest, approved and approvable revision."""
    problems: list[str] = []
    for kind, collection, refs, check in (
        ("finding", "ai_findings", manifest["findings"], finding_problems),
        ("review", "ai_review_excerpts", manifest["reviews"], review_problems),
    ):
        for ref in refs:
            latest = db[collection].find_one({"id": ref["id"]}, sort=[("revision", -1)], session=session)
            if latest is None or latest["revision"] != ref["revision"]:
                problems.append(f"{kind} {ref['id']} has a newer revision")
            elif latest["review_status"] != "approved":
                problems.append(f"{kind} {ref['id']} is {latest['review_status']}")
            else:
                problems += [f"{kind} {ref['id']}: {p}" for p in check(db, latest, session)]
    return problems


def _revision(
    db: Database[dict[str, Any]], revision_id: str, number: int, session: ClientSession | None
) -> dict[str, Any]:
    doc = db[REVISIONS].find_one({"_id": revision_id}, session=session)
    if doc is None:
        raise ApiError(404, "not_found", "Not found")
    if doc["revision"] != number:
        raise ApiError(
            409,
            "version_conflict",
            f"This is revision {doc['revision']}, not {number}",
            current_version=doc["revision"],
        )
    latest = _latest(db, doc["project_id"], doc["locale"], session)
    if latest["_id"] != doc["_id"]:
        raise ApiError(
            409,
            "version_conflict",
            f"Revision {latest['revision']} is newer; review that one",
            current_version=latest["revision"],
        )
    return dict(doc)


def approve(
    db: Database[dict[str, Any]],
    contracts: ContractStore,
    revision_id: str,
    body: dict[str, Any],
    actor: dict[str, Any],
) -> dict[str, Any]:
    if actor.get("kind") != "user" or actor.get("role") != "moderator":
        raise ApiError(403, "forbidden", "Only a moderator can approve page content")

    def write(session: ClientSession) -> str:
        doc = _revision(db, revision_id, body["revision"], session)
        if not contracts.transition_allowed("content_lifecycle", doc["lifecycle"], "approved", "moderator"):
            raise ApiError(409, "invalid_transition", f"A {doc['lifecycle']} revision cannot be approved")
        payload_sha, manifest_sha = content_hash(doc["payload"]), content_hash(doc["manifest"])
        if payload_sha != doc["payload_sha256"] or manifest_sha != doc["manifest_sha256"]:
            raise ApiError(
                409, "hash_mismatch", "The stored revision no longer matches its hashes; it cannot be approved"
            )
        if body["payload_sha256"] != payload_sha or body["manifest_sha256"] != manifest_sha:
            raise ApiError(409, "hash_mismatch", "The hashes you approved are not this revision's; reload it")
        state = publication_state(db, doc["project_id"], doc["locale"], session)
        if state["pending_invalidation"]:
            raise ApiError(409, "ineligible_dependency", "An evidence invalidation is pending for this project")
        if body["eligibility_epoch"] != state["eligibility_epoch"]:
            raise ApiError(
                409, "version_conflict", "Evidence eligibility changed since you loaded this revision; reload it"
            )
        if body["expected_state_version"] != state["version"]:
            raise ApiError(
                409, "version_conflict", "The publication state changed; reload it", current_version=state["version"]
            )
        if doc["manifest"]["eligibility_epoch"] != state["eligibility_epoch"]:
            raise ApiError(
                409,
                "ineligible_dependency",
                "The revision was built before an evidence change; generate or edit it again",
            )
        problems = dependency_problems(db, doc["manifest"], session)
        if problems:
            raise ApiError(409, "ineligible_dependency", "Cannot approve: " + "; ".join(problems)[:500])
        binding = {
            "project_id": doc["project_id"],
            "locale": doc["locale"],
            "payload_sha256": payload_sha,
            "manifest_sha256": manifest_sha,
            "eligibility_epoch": state["eligibility_epoch"],
            "expected_state_version": state["version"],
        }
        decision_id = record_decision(
            db,
            target_type="content_revision",
            target_id=revision_id,
            revision=doc["revision"],
            action="approve",
            reason=None,
            actor=actor,
            session=session,
            binding=binding,
        )
        changed = db[REVISIONS].update_one(
            {"_id": revision_id, "lifecycle": "final_review"}, {"$set": {"lifecycle": "approved"}}, session=session
        )
        if changed.modified_count != 1:
            raise ApiError(409, "version_conflict", "The revision changed; reload it")
        db[REVISIONS].update_many(
            {
                "project_id": doc["project_id"],
                "locale": doc["locale"],
                "_id": {"$ne": revision_id},
                "lifecycle": "approved",
            },
            {"$set": {"lifecycle": "superseded"}},
            session=session,
        )
        moved = db[STATES].update_one(
            {"_id": state["_id"], "version": state["version"], "eligibility_epoch": state["eligibility_epoch"]},
            {
                "$set": {
                    "approved": {
                        "revision_id": revision_id,
                        "revision": doc["revision"],
                        "payload_sha256": payload_sha,
                        "manifest_sha256": manifest_sha,
                        "decision_id": decision_id,
                    },
                    "updated_at": utcnow(),
                },
                "$inc": {"version": 1},
            },
            session=session,
        )
        if moved.modified_count != 1:
            raise ApiError(409, "version_conflict", "The publication state changed; reload it")
        audit.record(
            db,
            "content.approved",
            "content_revision",
            revision_id,
            actor,
            revision=doc["revision"],
            details={"payload_sha256": payload_sha, "eligibility_epoch": state["eligibility_epoch"]},
            session=session,
        )
        return decision_id

    decision_id = run_in_transaction(db.client, write)
    doc = db[REVISIONS].find_one({"_id": revision_id}) or {}
    _move_run(
        db,
        contracts,
        doc.get("project_id", ""),
        "approved",
        "moderator",
        f"Revision {doc.get('revision')} approved",
        actor,
    )
    view = to_view(db["ai_review_decisions"].find_one({"_id": decision_id}))
    assert view is not None
    return view


def decide(
    db: Database[dict[str, Any]],
    contracts: ContractStore,
    revision_id: str,
    body: dict[str, Any],
    actor: dict[str, Any],
) -> dict[str, Any]:
    to = "rejected" if body["action"] == "reject" else "changes_requested"

    def write(session: ClientSession) -> str:
        doc = _revision(db, revision_id, body["revision"], session)
        if not contracts.transition_allowed("content_lifecycle", doc["lifecycle"], to, actor["role"]):
            raise ApiError(409, "invalid_transition", f"A {doc['lifecycle']} revision cannot be moved to {to}")
        decision_id = record_decision(
            db,
            target_type="content_revision",
            target_id=revision_id,
            revision=doc["revision"],
            action=body["action"],
            reason=body["reason"],
            actor=actor,
            session=session,
        )
        changed = db[REVISIONS].update_one(
            {"_id": revision_id, "lifecycle": doc["lifecycle"]}, {"$set": {"lifecycle": to}}, session=session
        )
        if changed.modified_count != 1:
            raise ApiError(409, "version_conflict", "The revision changed; reload it")
        audit.record(
            db,
            "content.decided",
            "content_revision",
            revision_id,
            actor,
            revision=doc["revision"],
            details={"action": body["action"], "to": to},
            session=session,
        )
        return decision_id

    decision_id = run_in_transaction(db.client, write)
    if to == "changes_requested":
        doc = db[REVISIONS].find_one({"_id": revision_id}) or {}
        _move_run(
            db,
            contracts,
            doc.get("project_id", ""),
            "formatting",
            "moderator",
            "Changes requested on the page content",
            actor,
        )
    view = to_view(db["ai_review_decisions"].find_one({"_id": decision_id}))
    assert view is not None
    return view
