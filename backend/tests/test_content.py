# ruff: noqa: F811  (the scripted `model` fixture is imported from the workflow tests)
"""UC-68..UC-75: page content, final approval and publication (Steps 10 and 11 core; docs/05; D23, D28, D64, D66).

Against the scripted model of the workflow tests (no live call): a page from reviews alone needs no model; a page
from findings cites only approved revisions and keeps their caveats; QA blocks an opinion written as a fact, a new
number, a lost caveat, occupancy wording before possession and a changed review; an edit is a new revision whose
hash an older approval cannot authorise; approval binds hash, epoch and state version; publication activates once,
is verified from the rendered page and never shows a draft; withdrawn evidence stops serving and cannot be rolled
back to; unpublish serves the empty state."""

from __future__ import annotations

import copy

import httpx
import pytest
from pydantic import SecretStr

from app.content import service
from app.content.build import REVIEWS_ATTRIBUTION
from app.content.hashing import content_hash
from app.content.qa import check_payload
from app.publication import service as publication
from app.workflows import analysis

from .conftest import sign_in
from .test_workflow import MODERATOR, analysing_run, approve_all, model, work  # noqa: F401


def generated(db, settings, contracts, fictional, *, findings=True):
    """A project whose analysis waited for review, everything approved, and content generated from the selection."""
    q, run = analysing_run(db, settings, contracts, fictional)
    work(db)
    approve_all(db, q)
    body = {
        "mode": "generate",
        "locale": "en-IN",
        "findings": [{"id": f["id"], "revision": f["revision"]} for f in db["ai_findings"].find({"project_id": q})]
        if findings
        else [],
        "reviews": [
            {"id": r["id"], "revision": r["revision"]} for r in db["ai_review_excerpts"].find({"project_id": q})
        ],
    }
    analysis.request_resume(db, q, body, MODERATOR)
    assert work(db) == ["completed"]
    run = db["ai_runs"].find_one({"_id": run["_id"]})
    revision = db["ai_content_revisions"].find_one({"_id": run["content_revision_id"]})
    return q, run, revision


def basis_for(db, revision):
    project = db["projects"].find_one({"_id": revision["project_id"]})
    config = db["ai_project_configs"].find_one({"_id": revision["project_id"]})
    findings = [db["ai_findings"].find_one(r) for r in revision["manifest"]["findings"]]
    reviews = [db["ai_review_excerpts"].find_one(r) for r in revision["manifest"]["reviews"]]
    basis, _, _ = service._basis(db, project, config, findings, reviews, None)
    return basis


def test_a_page_from_reviews_alone_needs_no_model(db, settings, contracts, fictional, model):
    q, run, revision = generated(db, settings, contracts, fictional, findings=False)
    assert "A08" not in model.calls and "A09" not in model.calls, "D64: the authors' words need no model"
    assert run["stage"] == "final_review" and revision["lifecycle"] == "final_review"
    payload = revision["payload"]
    assert payload["overview"] is None and payload["advantages"] == [] and payload["sources"] == []
    assert payload["attribution"] == REVIEWS_ATTRIBUTION
    approved = {r["id"]: r for r in db["ai_review_excerpts"].find({"project_id": q})}
    for shown in payload["reviews"]:
        record = approved[shown["support"]["review"]["id"]]
        assert shown["text"] == record["text"] and shown["source_url"] is None, "the approved words, no public link"
        assert shown["credit"]["speaker_label"] == record["speaker_label"]
    assert revision["payload_sha256"] == content_hash(payload) and revision["manifest"]["findings"] == []
    assert "aggregateRating" not in str(payload["json_ld"]) and "Review" not in str(payload["json_ld"])
    view = service.revision_view(db, revision)
    assert contracts.errors(view, "api.schema.json#/$defs/ContentRevisionView") == []


def test_a_page_from_findings_cites_only_approved_revisions_and_keeps_caveats(
    db,
    settings,
    contracts,
    fictional,
    model,
):
    q, _, revision = generated(db, settings, contracts, fictional)
    assert model.calls[-2:] == ["A08", "A09"] and revision["lifecycle"] == "final_review"
    payload, manifest = revision["payload"], revision["manifest"]
    allowed = {(f["id"], f["revision"]) for f in manifest["findings"]}
    for item in [payload["overview"], *payload["advantages"], *payload["considerations"]]:
        assert {(r["id"], r["revision"]) for r in item["support"]["findings"]} <= allowed
    findings = {f["id"]: f for f in db["ai_findings"].find({"project_id": q})}
    for item in payload["considerations"]:
        for ref in item["support"]["findings"]:
            for caveat in findings[ref["id"]]["caveats"]:
                assert caveat in (item["caveat"] or ""), "the finding's caveat travels with the item"
    assert payload["heading"] == f"What buyers say about {payload['project']['name']}", "model heading lacked the name"
    assert check_payload(payload, basis_for(db, revision)) == [] or all(
        i["severity"] == "nonblocking" for i in check_payload(payload, basis_for(db, revision))
    )


def test_qa_blocks_opinion_as_fact_new_numbers_lost_caveats_occupancy_and_changed_reviews(
    db,
    settings,
    contracts,
    fictional,
    model,
):
    _, _, revision = generated(db, settings, contracts, fictional)
    basis = basis_for(db, revision)
    original = revision["payload"]
    assert original["considerations"], "the scripted findings are cons"

    def blocking(change):
        payload = copy.deepcopy(original)
        change(payload)
        return {i["category"] for i in check_payload(payload, basis) if i["severity"] == "blocking"}

    def as_fact(p):
        p["considerations"][0]["text"] = "The approach road floods."

    def new_number(p):
        p["considerations"][0]["text"] += " It took 45 days."

    def lost_caveat(p):
        p["considerations"][0]["caveat"] = None

    def occupancy(p):
        p["coverage_note"] += " Residents agree."

    def changed_review(p):
        p["reviews"][0]["text"] = p["reviews"][0]["text"] + " Best project ever"

    def foreign_finding(p):
        p["considerations"][0]["support"]["findings"] = [{"id": "fnd_00000000000000000000000000", "revision": 1}]

    assert "attribution_lost" in blocking(as_fact), "an opinion rewritten as a universal fact"
    assert "number_mismatch" in blocking(new_number)
    if basis.findings and any(f["caveats"] for f in basis.findings.values()):
        assert "caveat_lost" in blocking(lost_caveat)
    assert "status_inconsistent" in blocking(occupancy), "residents before possession (under construction)"
    assert "review_meaning_changed" in blocking(changed_review)
    assert "unsupported_claim" in blocking(foreign_finding)


def approval_body(db, revision):
    state = service.publication_state(db, revision["project_id"])
    return {
        "revision": revision["revision"],
        "payload_sha256": revision["payload_sha256"],
        "manifest_sha256": revision["manifest_sha256"],
        "eligibility_epoch": state["eligibility_epoch"],
        "expected_state_version": state["version"],
    }


def test_final_approval_binds_hash_epoch_and_state_version(
    api,
    db,
    settings,
    contracts,
    fictional,
    model,
    make_user,
):
    q, _, revision = generated(db, settings, contracts, fictional, findings=False)
    url = f"/v1/content-revisions/{revision['_id']}/approvals"
    for roles in (["analyst"], ["researcher"], ["publisher"]):
        assert (
            api.post(url, json=approval_body(db, revision), headers=sign_in(api, make_user, roles)).status_code == 403
        )
    moderator = sign_in(api, make_user, ["moderator"])
    wrong = {**approval_body(db, revision), "payload_sha256": "sha256:" + "0" * 64}
    assert api.post(url, json=wrong, headers=moderator).json()["error"]["code"] == "hash_mismatch"
    stale = {**approval_body(db, revision), "expected_state_version": 7}
    assert api.post(url, json=stale, headers=moderator).status_code == 409
    epoch = {**approval_body(db, revision), "eligibility_epoch": 3}
    assert api.post(url, json=epoch, headers=moderator).status_code == 409
    approved = api.post(url, json=approval_body(db, revision), headers=moderator)
    assert approved.status_code == 201, approved.text
    decision = approved.json()
    assert contracts.errors(decision, "content.schema.json#/$defs/ReviewDecision") == []
    assert decision["binding"]["payload_sha256"] == revision["payload_sha256"] and decision["actor"]["kind"] == "user"
    state = service.publication_state(db, q)
    assert state["approved"]["revision_id"] == revision["_id"] and state["version"] == 1
    assert db["ai_content_revisions"].find_one({"_id": revision["_id"]})["lifecycle"] == "approved"
    again = api.post(url, json=approval_body(db, revision), headers=moderator)
    assert again.status_code == 409, "an approved revision is not approved twice"


def edit(api, headers, revision, change, reason="tighten the heading"):
    payload = copy.deepcopy(revision["payload"])
    change(payload)
    body = {
        "mode": "edit",
        "locale": "en-IN",
        "base": {"id": revision["_id"], "revision": revision["revision"]},
        "payload": payload,
        "reason": reason,
    }
    return api.post(
        f"/v1/projects/{revision['project_id']}/content-revisions",
        json=body,
        headers={**headers, "Idempotency-Key": f"edit-{revision['revision']}-{len(reason)}-x"},
    )


def test_an_edit_is_a_new_revision_and_an_old_approval_cannot_publish_it(
    api,
    db,
    settings,
    contracts,
    fictional,
    model,
    make_user,
):
    q, _, first = generated(db, settings, contracts, fictional, findings=False)
    both = sign_in(api, make_user, ["moderator", "publisher"])
    assert (
        api.post(
            f"/v1/content-revisions/{first['_id']}/approvals", json=approval_body(db, first), headers=both
        ).status_code
        == 201
    )
    first = db["ai_content_revisions"].find_one({"_id": first["_id"]})
    response = edit(api, both, first, lambda p: p.update(heading=p["heading"] + " in 2026"))
    assert response.status_code == 201, "an edit that fails a check is kept as a draft with the issue on its block"
    draft = response.json()
    assert draft["revision"]["lifecycle"] == "draft"
    assert [i["block"] for i in draft["qa_issues"] if i["category"] == "number_mismatch"] == ["heading"]
    draft_doc = db["ai_content_revisions"].find_one({"_id": draft["revision"]["id"]})
    response = edit(api, both, draft_doc, lambda p: p.update(heading="Buyers on " + p["project"]["name"]), "fix it")
    assert response.status_code == 201, response.text
    second = response.json()["revision"]
    assert second["revision"] == 3 and second["payload_sha256"] != first["payload_sha256"]
    assert second["supersedes"] == {"id": draft_doc["_id"], "revision": 2} and second["lifecycle"] == "final_review"
    assert db["ai_content_revisions"].find_one({"_id": draft_doc["_id"]})["lifecycle"] == "superseded"
    assert db["ai_content_revisions"].find_one({"_id": first["_id"]})["lifecycle"] == "approved", "until replaced"
    assert second["created_by"]["kind"] == "moderator"
    state = service.publication_state(db, q)
    publish_second = {
        "project_id": q,
        "locale": "en-IN",
        "revision_id": second["id"],
        "payload_sha256": second["payload_sha256"],
        "expected_state_version": state["version"],
    }
    refused = api.post("/v1/publications", json=publish_second, headers={**both, "Idempotency-Key": "publish-0002"})
    assert refused.status_code == 409 and refused.json()["error"]["code"] == "approval_required"
    stale_edit = edit(
        api, both, first, lambda p: p.update(heading="Again " + p["project"]["name"]), reason="stale base"
    )
    assert stale_edit.status_code == 409, "two editors cannot silently overwrite one another"
    reworded = edit(
        api,
        both,
        db["ai_content_revisions"].find_one({"_id": second["id"]}),
        lambda p: p["reviews"][0].update(text="New words"),
        "change a review",
    )
    assert reworded.status_code == 422 and "Nothing changed" in reworded.json()["error"]["message"], (
        "a review is always the approved record: rewording it changes nothing (D28)"
    )


class FakeWeb:
    """The web app as the delivery worker sees it: the revalidation route and the rendered public page."""

    def __init__(self, db, slug, marker="right"):
        self.db, self.slug, self.marker, self.revalidated = db, slug, marker, []

    def handler(self, request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/revalidate":
            self.revalidated.append(request.headers.get("X-Revalidate-Signature"))
            return httpx.Response(200, json={"revalidated": True})
        insights = publication.public_insights(self.db, self.slug)
        if insights is None:
            return httpx.Response(200, text='<section data-insights-state="empty"></section>')
        revision = insights["revision_id"] if self.marker == "right" else "rev_00000000000000000000000000"
        html = (
            f'<section data-insights-state="active" data-insights-revision="{revision}" '
            f'data-insights-hash="{insights["payload_sha256"]}"></section>'
        )
        return httpx.Response(200, text=html)

    def client(self):
        return httpx.Client(transport=httpx.MockTransport(self.handler), base_url="http://web.test")


def deliver(db, settings, web):
    settings.web_internal_url = "http://web.test"
    settings.revalidation_secret = SecretStr("x" * 40)
    statuses = []
    for job in db["ai_jobs"].find({"kind": "deliver_publication", "status": "queued"}):
        try:
            publication.handle_deliver(db, job, lambda: "ok", client=web.client(), settings=settings)
            db["ai_jobs"].update_one({"_id": job["_id"]}, {"$set": {"status": "completed"}})
            statuses.append("completed")
        except Exception as exc:  # the worker would retry
            statuses.append(type(exc).__name__)
    return statuses


def published(api, db, settings, contracts, fictional, make_user, both=None):
    q, _, revision = generated(db, settings, contracts, fictional, findings=False)
    both = both or sign_in(api, make_user, ["moderator", "publisher"])
    assert (
        api.post(
            f"/v1/content-revisions/{revision['_id']}/approvals", json=approval_body(db, revision), headers=both
        ).status_code
        == 201
    )
    state = service.publication_state(db, q)
    body = {
        "project_id": q,
        "locale": "en-IN",
        "revision_id": revision["_id"],
        "payload_sha256": revision["payload_sha256"],
        "expected_state_version": state["version"],
    }
    return q, revision, both, body


def test_publication_activates_once_and_is_verified_from_the_rendered_page(
    api,
    db,
    settings,
    contracts,
    fictional,
    model,
    make_user,
):
    q, revision, both, body = published(api, db, settings, contracts, fictional, make_user)
    slug = db["projects"].find_one({"_id": q})["slug"]
    assert api.get(f"/v1/public/projects/{slug}/insights").status_code == 404, "nothing is served before publication"
    first = api.post("/v1/publications", json=body, headers={**both, "Idempotency-Key": "publish-0001"})
    assert first.status_code == 202, first.text
    operation = first.json()
    assert contracts.errors(operation, "publication.schema.json#/$defs/PublicationOperation") == []
    assert operation["status"] == "delivery_pending" and operation["activated_at"] is not None
    assert (
        api.post("/v1/publications", json=body, headers={**both, "Idempotency-Key": "publish-0001"}).json() == operation
    )
    other = {**body, "expected_state_version": body["expected_state_version"] + 1}
    assert (
        api.post("/v1/publications", json=other, headers={**both, "Idempotency-Key": "publish-0001"}).status_code == 409
    )
    public = api.get(f"/v1/public/projects/{slug}/insights")
    assert public.status_code == 200 and public.json()["revision_id"] == revision["_id"]
    assert contracts.errors(public.json(), "api.schema.json#/$defs/PublicInsights") == []
    web = FakeWeb(db, slug)
    assert deliver(db, settings, web) == ["completed"] and web.revalidated[0]
    verified = db["ai_publication_operations"].find_one({"_id": operation["id"]})
    assert verified["status"] == "verified" and verified["verification"]["rendered_revision_id"] == revision["_id"]
    assert service.publication_state(db, q)["pending_intent"] is None
    view = api.get(f"/v1/projects/{q}/publication", headers=both)
    assert (
        view.status_code == 200 and contracts.errors(view.json(), "api.schema.json#/$defs/PublicationStateView") == []
    )
    # a newer draft never reaches the page
    current = db["ai_content_revisions"].find_one({"_id": revision["_id"]})
    assert edit(api, both, current, lambda p: p.update(heading="Buyers on " + p["project"]["name"])).status_code == 201
    assert api.get(f"/v1/public/projects/{slug}/insights").json()["revision_id"] == revision["_id"]


def test_a_page_showing_the_wrong_revision_is_never_reported_as_delivered(
    api,
    db,
    settings,
    contracts,
    fictional,
    model,
    make_user,
):
    q, _, both, body = published(api, db, settings, contracts, fictional, make_user)
    slug = db["projects"].find_one({"_id": q})["slug"]
    operation = api.post("/v1/publications", json=body, headers={**both, "Idempotency-Key": "publish-0003"}).json()
    web = FakeWeb(db, slug, marker="wrong")
    for _ in range(publication.MAX_DELIVERY_ATTEMPTS):
        db["ai_jobs"].update_many({"kind": "deliver_publication"}, {"$set": {"status": "queued"}})
        deliver(db, settings, web)
    stored = db["ai_publication_operations"].find_one({"_id": operation["id"]})
    assert stored["status"] == "failed" and stored["verification"]["verified_at"] is None
    assert service.publication_state(db, q)["serving_state"] == "active", "activation stands; delivery failed visibly"


def test_withdrawn_evidence_stops_serving_and_cannot_be_rolled_back_to(
    api,
    db,
    settings,
    contracts,
    fictional,
    model,
    make_user,
):
    q, revision, both, body = published(api, db, settings, contracts, fictional, make_user)
    slug = db["projects"].find_one({"_id": q})["slug"]
    operation = api.post("/v1/publications", json=body, headers={**both, "Idempotency-Key": "publish-0004"}).json()
    deliver(db, settings, FakeWeb(db, slug))
    source_id = revision["manifest"]["sources"][0]["id"]
    withdrawal = {"scope": "source_revision", "revision": 1, "reason": "Author asked"}
    accepted = api.post(
        f"/v1/sources/{source_id}/withdrawals", json=withdrawal, headers={**both, "Idempotency-Key": "withdraw-0004"}
    )
    assert accepted.status_code == 202, accepted.text
    work(db)
    state = service.publication_state(db, q)
    assert state["serving_state"] == "temporarily_disabled" and state["eligibility_epoch"] == 1
    assert api.get(f"/v1/public/projects/{slug}/insights").status_code == 404, "withdrawn content stops serving"
    assert db["ai_content_revisions"].find_one({"_id": revision["_id"]})["lifecycle"] == "withdrawn"
    rollback = {"target_revision_id": revision["_id"], "reason": "restore", "expected_state_version": state["version"]}
    refused = api.post(
        f"/v1/publications/{operation['id']}/rollback",
        json=rollback,
        headers={**both, "Idempotency-Key": "rollback-0004"},
    )
    assert refused.status_code == 409, "rollback can never revive withdrawn content"


def test_unpublish_serves_the_empty_state_and_is_verified(
    api,
    db,
    settings,
    contracts,
    fictional,
    model,
    make_user,
):
    q, revision, both, body = published(api, db, settings, contracts, fictional, make_user)
    slug = db["projects"].find_one({"_id": q})["slug"]
    api.post("/v1/publications", json=body, headers={**both, "Idempotency-Key": "publish-0005"})
    deliver(db, settings, FakeWeb(db, slug))
    state = service.publication_state(db, q)
    request = {
        "locale": "en-IN",
        "current_revision_id": revision["_id"],
        "reason": "Paused",
        "expected_state_version": state["version"],
    }
    response = api.post(f"/v1/projects/{q}/unpublish", json=request, headers={**both, "Idempotency-Key": "unpub-0005"})
    assert response.status_code == 202, response.text
    assert api.get(f"/v1/public/projects/{slug}/insights").status_code == 404
    assert deliver(db, settings, FakeWeb(db, slug)) == ["completed"]
    assert db["ai_publication_operations"].find_one({"_id": response.json()["id"]})["status"] == "verified"


@pytest.mark.parametrize("roles", [["analyst"], ["moderator"]])
def test_publication_writes_need_the_publisher_role(api, db, make_user, fictional, roles):
    headers = {**sign_in(api, make_user, roles), "Idempotency-Key": "publish-roles"}
    q = fictional["Quillon Residences"]
    body = {
        "project_id": q,
        "locale": "en-IN",
        "revision_id": "rev_00000000000000000000000000",
        "payload_sha256": "sha256:" + "0" * 64,
        "expected_state_version": 0,
    }
    assert api.post("/v1/publications", json=body, headers=headers).status_code == 403
