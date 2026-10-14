# ruff: noqa: F811  (the scripted `model` fixture is imported from the workflow tests)
"""UC-76..UC-81: the Step 09 console API. Edits are new revisions under the evidence rules (an opinion cannot be
relabelled a fact, no new numbers, required caveats stay, a review keeps the author's words); stale bases conflict;
users and roles are admin-only and an admin cannot lock themselves out; audit and evaluations are read-only; the
public correction form is rate-limited with a honeypot and moderators resolve or dismiss; a researcher can add one
project from the console (D58) and the portfolio row shows real run, review and publication data."""

from __future__ import annotations

from app.agents.findings import _caveats, attribution_for
from app.evidence.clusters import independent_origins

from .conftest import login, sign_in
from .test_workflow import analysing_run, model, work  # noqa: F401


def findings_and_reviews(db, settings, contracts, fictional):
    q, _ = analysing_run(db, settings, contracts, fictional)
    work(db)
    finding = db["ai_findings"].find_one({"project_id": q})
    review = db["ai_review_excerpts"].find_one({"project_id": q})
    return q, finding, review


def finding_edit(db, finding, **changes):
    claims = [db["ai_claims"].find_one({"id": c["id"], "revision": c["revision"]}) for c in finding["claims"]]
    origins = independent_origins(db, [e for c in claims for e in c["supporting_evidence"]])
    attribution = attribution_for(claims, len(origins))
    body = {
        "base": {"id": finding["id"], "revision": finding["revision"]},
        "kind": finding["kind"],
        "aspect": finding["aspect"],
        "wording": "Some site visitors say the approach road is poor.",
        "attribution": attribution,
        "claims": finding["claims"],
        "caveats": _caveats([], claims, attribution, len(origins)),
        "reason": "clearer wording",
    }
    return {**body, **changes}


def test_a_finding_edit_is_a_new_revision_that_keeps_the_evidence_rules(
    api, db, settings, contracts, fictional, model, make_user
):
    _, finding, _ = findings_and_reviews(db, settings, contracts, fictional)
    url = f"/v1/findings/{finding['id']}/revisions"
    analyst = sign_in(api, make_user, ["analyst"])
    assert api.post(url, json=finding_edit(db, finding), headers=analyst).status_code == 403
    moderator = sign_in(api, make_user, ["moderator"])
    fact = api.post(url, json=finding_edit(db, finding, attribution="verified_fact"), headers=moderator)
    assert fact.status_code == 422 and "attribution" in fact.json()["error"]["message"], "an opinion stays an opinion"
    number = api.post(
        url, json=finding_edit(db, finding, wording="Visitors say the road took 37 days."), headers=moderator
    )
    assert number.status_code == 422 and "37" in number.json()["error"]["message"]
    required = finding_edit(db, finding)["caveats"]
    if required:
        dropped = api.post(url, json=finding_edit(db, finding, caveats=[]), headers=moderator)
        assert dropped.status_code == 422 and "caveat" in dropped.json()["error"]["message"]
    created = api.post(url, json=finding_edit(db, finding), headers=moderator)
    assert created.status_code == 201, created.text
    revision = created.json()
    assert contracts.errors(revision, "evidence.schema.json#/$defs/Finding") == []
    assert revision["revision"] == finding["revision"] + 1 and revision["review_status"] == "pending"
    assert revision["created_by"]["kind"] == "moderator" and revision["supersedes"]["revision"] == finding["revision"]
    old = db["ai_findings"].find_one({"id": finding["id"], "revision": finding["revision"]})
    assert old["review_status"] == "superseded", "earlier decisions are labelled superseded"
    stale = api.post(url, json=finding_edit(db, finding), headers=moderator)
    assert stale.status_code == 409 and stale.json()["error"]["code"] == "version_conflict"
    assert db["ai_audit_events"].count_documents({"action": "finding.revised", "target.id": finding["id"]}) == 1


def test_a_review_edit_keeps_the_authors_words_from_the_same_source(
    api, db, settings, contracts, fictional, model, make_user
):
    q, _, review = findings_and_reviews(db, settings, contracts, fictional)
    url = f"/v1/review-excerpts/{review['id']}/revisions"
    moderator = sign_in(api, make_user, ["moderator"])
    base = {"base": {"id": review["id"], "revision": review["revision"]}, "evidence": review["evidence"]}
    added = {**base, "rendering": "verbatim", "text": review["text"] + " Truly great", "reason": "x"}
    assert api.post(url, json=added, headers=moderator).status_code == 422, "no words the author did not write"
    dashed = {**base, "rendering": "verbatim", "text": review["text"].replace(" ", " - ", 1), "reason": "x"}
    assert api.post(url, json=dashed, headers=moderator).status_code == 422
    other = db["ai_evidence"].find_one({"project_id": q, "source": {"$ne": review["source"]}})
    if other is not None:
        foreign = {**base, "evidence": [{"id": other["id"], "revision": other["revision"]}]}
        foreign |= {"rendering": "verbatim", "text": review["text"], "reason": "x"}
        assert api.post(url, json=foreign, headers=moderator).status_code == 422, "one review, one source"
    same = {**base, "rendering": review["rendering"], "text": review["text"], "reason": "recheck"}
    created = api.post(url, json=same, headers=moderator)
    assert created.status_code == 201, created.text
    assert contracts.errors(created.json(), "evidence.schema.json#/$defs/ReviewExcerpt") == []
    assert created.json()["review_status"] == "pending" and created.json()["revision"] == review["revision"] + 1
    assert db["ai_review_excerpts"].find_one({"_id": review["_id"]})["review_status"] == "superseded"


def test_users_and_roles_are_admin_only_and_an_admin_cannot_lock_themselves_out(
    api, db, settings, make_user, contracts
):
    researcher = sign_in(api, make_user, ["researcher"])
    assert api.get("/v1/admin/users", headers=researcher).status_code == 403
    body = {"email": "Editor@Example.test", "display_name": "Editor", "roles": ["moderator"], "password": "x" * 14}
    assert api.post("/v1/admin/users", json=body, headers=researcher).status_code == 403
    admin_user = make_user(["admin"])
    admin = {"X-CSRF-Token": login(api, admin_user["email"])["csrf_token"]}
    created = api.post("/v1/admin/users", json=body, headers=admin)
    assert created.status_code == 201 and created.json()["email"] == "editor@example.test"
    assert contracts.errors(created.json(), "api.schema.json#/$defs/UserView") == []
    assert "password" not in str(created.json()) and "hash" not in str(created.json())
    assert api.post("/v1/admin/users", json=body, headers=admin).status_code == 409
    assert (
        api.post(
            "/v1/admin/users", json={**body, "email": "b@example.test", "password": "short"}, headers=admin
        ).status_code
        == 422
    )
    page = api.get("/v1/admin/users", headers=admin)
    assert page.status_code == 200 and contracts.errors(page.json(), "api.schema.json#/$defs/UserPage") == []
    me = admin_user["_id"]
    assert api.patch(f"/v1/admin/users/{me}", json={"active": False}, headers=admin).status_code == 422
    assert api.patch(f"/v1/admin/users/{me}", json={"roles": ["moderator"]}, headers=admin).status_code == 422
    editor = created.json()["id"]
    from app.auth.sessions import create_session

    create_session(db, settings, editor)  # the editor is signed in somewhere
    changed = api.patch(
        f"/v1/admin/users/{editor}", json={"active": False, "roles": ["moderator", "publisher"]}, headers=admin
    )
    assert changed.status_code == 200 and changed.json()["active"] is False
    assert db["sessions"].count_documents({"user_id": editor}) == 0, "deactivation ends the user's sessions"
    audit = api.get("/v1/admin/audit-events?target_type=user", headers=admin)
    assert audit.status_code == 200 and contracts.errors(audit.json(), "api.schema.json#/$defs/AuditEventPage") == []
    assert {e["action"] for e in audit.json()["items"]} >= {"user.created", "user.updated"}


def test_evaluations_are_listed_with_their_sample_sizes(api, db, make_user, contracts):
    from app.db import utcnow

    db["ai_evaluations"].insert_one(
        {
            "_id": "evl_01K00000000000000000000001",
            "dataset": {"name": "agents-synthetic", "version": "1.0.0", "synthetic": True},
            "config": {"agent": None, "model": "scripted", "prompt_version": "a", "schema_version": "1.1.0"},
            "status": "completed",
            "metrics": [{"name": "recall", "value": 1.0, "sample_size": 12, "note": "synthetic"}],
            "created_at": utcnow(),
        }
    )
    page = api.get("/v1/evaluations", headers=sign_in(api, make_user, ["analyst"]))
    assert page.status_code == 200 and contracts.errors(page.json(), "api.schema.json#/$defs/EvaluationPage") == []
    assert page.json()["items"][0]["metrics"][0]["sample_size"] == 12


def test_public_corrections_are_rate_limited_and_moderated(api, db, settings, make_user, fictional, contracts):
    settings.corrections_per_hour = 2
    slug = db["projects"].find_one({"_id": fictional["Quillon Residences"]})["slug"]
    url = f"/v1/public/projects/{slug}/corrections"
    report = {"message": "The possession date shown is wrong.", "contact": None, "revision_id": None, "website": ""}
    assert api.post(url, json={**report, "website": "http://spam.test"}).status_code == 422, "honeypot"
    assert api.post("/v1/public/projects/no-such-project/corrections", json=report).status_code == 404
    first = api.post(url, json=report)
    assert first.status_code == 202 and contracts.errors(first.json(), "api.schema.json#/$defs/CorrectionAck") == []
    assert api.post(url, json=report).status_code == 202
    assert api.post(url, json=report).status_code == 429, "per-address limit"
    assert api.get("/v1/corrections", headers=sign_in(api, make_user, ["analyst"])).status_code == 403
    moderator = sign_in(api, make_user, ["moderator"])
    page = api.get("/v1/corrections?status=received", headers=moderator)
    assert page.status_code == 200 and contracts.errors(page.json(), "api.schema.json#/$defs/CorrectionPage") == []
    assert len(page.json()["items"]) == 2
    correction = first.json()["correction_id"]
    decided = api.post(
        f"/v1/corrections/{correction}/decisions", json={"action": "resolve", "reason": "fixed"}, headers=moderator
    )
    assert decided.status_code == 200 and decided.json()["target"]["type"] == "correction"
    again = api.post(
        f"/v1/corrections/{correction}/decisions", json={"action": "dismiss", "reason": "x"}, headers=moderator
    )
    assert again.status_code == 409, "a resolved correction stays resolved"
    projects = api.get("/v1/projects", headers=moderator).json()["items"]
    row = next(p for p in projects if p["project"]["slug"] == slug)
    assert row["pending_review"]["corrections"] == 1


def test_a_researcher_adds_one_project_from_the_console(api, db, make_user, contracts):
    body = {
        "project_name": "Example Heights",
        "alternate_names": ["Ex Heights"],
        "locality": "Hinjewadi",
        "city": "Pune",
        "state": "Maharashtra",
        "micromarket": None,
        "developer": None,
        "rera_ids": [],
    }
    analyst = sign_in(api, make_user, ["analyst"])
    assert (
        api.post("/v1/projects", json=body, headers={**analyst, "Idempotency-Key": "add-project-1"}).status_code == 403
    )
    researcher = sign_in(api, make_user, ["researcher"])
    assert api.post("/v1/projects", json=body, headers=researcher).status_code == 422, "Idempotency-Key required"
    created = api.post("/v1/projects", json=body, headers={**researcher, "Idempotency-Key": "add-project-1"})
    assert created.status_code == 201, created.text
    row = created.json()["projects"][0]
    assert row["created"] and row["slug"] == "example-heights-hinjewadi-pune"
    again = api.post("/v1/projects", json=body, headers={**researcher, "Idempotency-Key": "add-project-1"})
    assert again.json() == created.json(), "the same request is answered once"
    duplicate = api.post("/v1/projects", json=body, headers={**researcher, "Idempotency-Key": "add-project-2"})
    assert duplicate.status_code == 409, "the console never updates an existing project"
    project = db["projects"].find_one({"_id": row["project_id"]})
    config = db["ai_project_configs"].find_one({"_id": row["project_id"]})
    assert project["state"] == "Maharashtra" and config
    sources = {s["connector_id"]: s["enabled"] for s in config["sources"]}
    # Every mandatory source is on from the start, Reddit included (D67): a run from the console uses it at once.
    assert sources["reddit_public"] and sources["brave_search"] and sources["web_fetch"] and sources["youtube_data_api"]
    page = api.get("/v1/projects", headers=researcher)
    assert page.status_code == 200 and contracts.errors(page.json(), "api.schema.json#/$defs/ProjectPage") == []
    listed = next(p for p in page.json()["items"] if p["project"]["id"] == row["project_id"])
    assert listed["latest_run"] is None and listed["publication"]["serving_state"] == "unpublished"
