"""UC-28: source links, evidence spans and match corrections on the replica set (Step 04.5, 04.6; journeys
J04, J18). Fictional catalogue and texts only."""

from __future__ import annotations

from app.identity.evidence import usable_for_identity
from app.identity.intake import store_text_source
from app.identity.invalidation import handle as invalidate
from app.identity.service import identify_source
from app.identity.text import sha256_text

from .conftest import sign_in

COMPARISON = (
    "Comparing two options.\n\nQuillon Residences in Sector 102: bigger balconies.\n\n"
    "Tavira Vista in Sector 88: better finishing."
)


def store(db, settings, text, native_id="post-1"):
    return store_text_source(
        db,
        connector_id="firecrawl",
        native_id=native_id,
        canonical_url=f"https://forum.example.test/{native_id}",
        source_kind="forum_post",
        text=text,
        policy_family="web_public_pages",
        language="en",
    )


def identify(db, contracts, settings, source, focus):
    return identify_source(db.client, db, contracts, source, focus_project_ids=focus)


def link_of(db, project_id, **extra):
    return db["ai_project_source_links"].find_one({"project_id": project_id, **extra})


def test_a_matched_source_gets_a_contract_valid_link_and_evidence(db, contracts, settings, fictional):
    q = fictional["Quillon Residences"]
    source = store(db, settings, "Visited Quillon Residences in Sector 102 last weekend.")
    report = identify(db, contracts, settings, source, [q])
    [row] = report["links"]
    assert row["status"] == "auto_accepted" and row["project_id"] == q
    from app.identity.links import link_view

    link = link_of(db, q)
    assert contracts.errors(link_view(link), "sources.schema.json#/$defs/ProjectSourceLink") == []
    evidence = db["ai_evidence"].find_one({"link_id": link["_id"]})
    view = {k: v for k, v in evidence.items() if k != "_id"}
    view["created_at"] = "2026-09-28T00:00:00Z"
    assert contracts.errors(view, "evidence.schema.json#/$defs/Evidence") == []
    assert evidence["excerpt_sha256"] == sha256_text(evidence["excerpt_text"])
    assert usable_for_identity(db, evidence)


def test_identifying_again_changes_nothing(db, contracts, settings, fictional):
    q = fictional["Quillon Residences"]
    source = store(db, settings, "Visited Quillon Residences in Sector 102 last weekend.")
    identify(db, contracts, settings, source, [q])
    again = identify(
        db, contracts, settings, store(db, settings, "Visited Quillon Residences in Sector 102 last weekend."), [q]
    )
    assert [r["created"] for r in again["links"]] == [False]
    assert db["ai_sources"].count_documents({}) == 1 and db["ai_project_source_links"].count_documents({}) == 1


def test_a_comparison_links_two_projects_without_duplicating_the_source(db, contracts, settings, fictional):
    q, t = fictional["Quillon Residences"], fictional["Tavira Vista"]
    identify(db, contracts, settings, store(db, settings, COMPARISON), [q])
    assert db["ai_sources"].count_documents({}) == 1
    links = {lk["project_id"]: lk for lk in db["ai_project_source_links"].find()}
    assert set(links) == {q, t}
    assert links[q]["source"] == links[t]["source"] and links[q]["segment_key"] != links[t]["segment_key"]
    assert all(lk["segment_key"].startswith("c:") for lk in links.values())


def test_a_rejected_focus_project_gets_no_evidence(db, contracts, settings, fictional):
    z = fictional["Zephyrine Crest"]
    identify(db, contracts, settings, store(db, settings, "Traffic diversions near Sector 65 this weekend."), [z])
    link = link_of(db, z)
    assert link["status"] == "rejected" and db["ai_evidence"].count_documents({"link_id": link["_id"]}) == 0


def test_moderator_rejects_a_wrong_match_and_dependants_are_invalidated(
    api, db, contracts, settings, fictional, make_user
):
    q = fictional["Quillon Residences"]
    identify(db, contracts, settings, store(db, settings, "Visited Quillon Residences in Sector 102."), [q])
    link = link_of(db, q)
    headers = sign_in(api, make_user, ["moderator"])
    body = {
        "action": "reject",
        "expected_version": link["version"],
        "reason": "Same name, different project",
        "split_segments": None,
        "remap_project_id": None,
        "phase_rera_id": None,
    }
    response = api.post(f"/v1/project-source-links/{link['_id']}/decisions", json=body, headers=headers)
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "rejected" and response.json()["decided_by"].startswith("dec_")
    assert contracts.errors(response.json(), "sources.schema.json#/$defs/ProjectSourceLink") == []
    evidence = db["ai_evidence"].find_one({"link_id": link["_id"]})
    assert not usable_for_identity(db, evidence), "evidence on a rejected link is ineligible at once"
    job = db["ai_jobs"].find_one({"kind": "invalidate_dependencies"})
    assert job is not None and link["_id"] in job["logical_key"] and job["project_id"] == q
    invalidate(db, job, lambda: "ok")
    audit = db["ai_audit_events"].find_one({"action": "dependencies.invalidated"})
    assert audit["details"]["evidence_made_ineligible"] == 1
    decision = db["ai_review_decisions"].find_one({"_id": response.json()["decided_by"]})
    assert decision["actor"]["role"] == "moderator" and decision["reason"] == "Same name, different project"


def test_accept_with_a_phase_and_version_and_role_checks(api, db, contracts, settings, fictional, make_user):
    q = fictional["Quillon Residences"]
    identify(db, contracts, settings, store(db, settings, "Quillon Residences, Gurgaon: any updates?"), [q])
    link = link_of(db, q)
    assert link["status"] == "needs_review"
    body = {
        "action": "accept",
        "expected_version": link["version"],
        "reason": None,
        "split_segments": None,
        "remap_project_id": None,
        "phase_rera_id": "TST/901/801/2023/11",
    }
    analyst = sign_in(api, make_user, ["analyst"])
    assert api.post(f"/v1/project-source-links/{link['_id']}/decisions", json=body, headers=analyst).status_code == 403
    headers = sign_in(api, make_user, ["moderator"])
    stale = {**body, "expected_version": link["version"] + 5}
    conflict = api.post(f"/v1/project-source-links/{link['_id']}/decisions", json=stale, headers=headers)
    assert conflict.status_code == 409 and conflict.json()["error"]["current_version"] == link["version"]
    wrong_phase = {**body, "phase_rera_id": "TST/903/803/2024/13"}  # Tavira Vista's registration
    refused = api.post(f"/v1/project-source-links/{link['_id']}/decisions", json=wrong_phase, headers=headers)
    assert refused.status_code == 422 and refused.json()["error"]["fields"][0]["path"] == "phase_rera_id"
    response = api.post(f"/v1/project-source-links/{link['_id']}/decisions", json=body, headers=headers)
    assert response.status_code == 200
    assert response.json()["phase"] == {"rera_id": "TST/901/801/2023/11", "certainty": "known"}
    assert db["ai_review_decisions"].count_documents({}) == 1, "refused requests leave no decision behind"


def test_split_a_whole_link_into_two_projects(api, db, contracts, settings, fictional, make_user):
    q, t = fictional["Quillon Residences"], fictional["Tavira Vista"]
    text = "Quillon Residences and Tavira Vista, both by Brightwell Estates. Q is bigger. T is nicer."
    source = store(db, settings, text)
    identify(db, contracts, settings, source, [q])
    link = link_of(db, q)
    assert link["status"] == "needs_review" and link["segment_key"] == "whole"
    first, second = (0, 65), (66, len(text))

    def segment(project_id, start, end):
        anchor = {
            "kind": "text",
            "representation": "original",
            "unit": "codepoint",
            "start": start,
            "end": end,
            "excerpt_sha256": sha256_text(text[start:end]),
        }
        return {"segment_key": f"c:{start}-{end}", "anchor": anchor, "project_id": project_id}

    headers = sign_in(api, make_user, ["moderator"])
    body = {
        "action": "split",
        "expected_version": link["version"],
        "reason": "Two projects in one post",
        "split_segments": [segment(q, *first), segment(t, *second)],
        "remap_project_id": None,
        "phase_rera_id": None,
    }
    response = api.post(f"/v1/project-source-links/{link['_id']}/decisions", json=body, headers=headers)
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "superseded" and len(response.json()["superseded_by"]) == 2
    new_links = list(db["ai_project_source_links"].find({"_id": {"$in": response.json()["superseded_by"]}}))
    assert {lk["project_id"] for lk in new_links} == {q, t} and {lk["status"] for lk in new_links} == {"accepted"}
    assert db["ai_evidence"].count_documents({"link_id": {"$in": [lk["_id"] for lk in new_links]}}) == 2
    tampered = segment(q, 0, 10)
    tampered["anchor"]["excerpt_sha256"] = sha256_text("something else")
    again = {**body, "expected_version": response.json()["version"], "split_segments": [tampered, segment(t, 11, 20)]}
    assert api.post(f"/v1/project-source-links/{link['_id']}/decisions", json=again, headers=headers).status_code in (
        409,
        422,
    )


def test_remap_moves_the_segment_to_another_project(api, db, contracts, settings, fictional, make_user):
    q, s = fictional["Quillon Residences"], fictional["Solvane Heights"]
    identify(db, contracts, settings, store(db, settings, "Visited Quillon Residences in Sector 102."), [q])
    link = link_of(db, q)
    headers = sign_in(api, make_user, ["moderator"])
    body = {
        "action": "remap",
        "expected_version": link["version"],
        "reason": "The post is really about Solvane",
        "split_segments": None,
        "remap_project_id": s,
        "phase_rera_id": None,
    }
    response = api.post(f"/v1/project-source-links/{link['_id']}/decisions", json=body, headers=headers)
    assert response.status_code == 200 and response.json()["status"] == "superseded"
    moved = link_of(db, s)
    assert moved["status"] == "accepted" and moved["match"]["method"] == "moderator"
    assert db["ai_jobs"].count_documents({"kind": "invalidate_dependencies"}) == 1, (
        "the auto-accepted link left service"
    )


def test_decisions_follow_the_state_machine_and_the_contract(api, db, contracts, settings, fictional, make_user):
    q = fictional["Quillon Residences"]
    identify(db, contracts, settings, store(db, settings, "Visited Quillon Residences in Sector 102."), [q])
    link = link_of(db, q)
    headers = sign_in(api, make_user, ["moderator"])
    no_reason = {
        "action": "reject",
        "expected_version": link["version"],
        "reason": None,
        "split_segments": None,
        "remap_project_id": None,
        "phase_rera_id": None,
    }
    assert (
        api.post(f"/v1/project-source-links/{link['_id']}/decisions", json=no_reason, headers=headers).status_code
        == 422
    )
    body = {**no_reason, "action": "remap", "reason": "wrong", "remap_project_id": fictional["Tavira Vista"]}
    first = api.post(f"/v1/project-source-links/{link['_id']}/decisions", json=body, headers=headers)
    assert first.status_code == 200
    accept = {**no_reason, "action": "accept", "expected_version": first.json()["version"]}
    blocked = api.post(f"/v1/project-source-links/{link['_id']}/decisions", json=accept, headers=headers)
    assert blocked.status_code == 409 and blocked.json()["error"]["code"] == "invalid_transition"
    assert api.post("/v1/project-source-links/not-an-id/decisions", json=accept, headers=headers).status_code == 404
