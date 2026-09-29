"""UC-29: alternate-name and phase-name proposals (Step 04.7, D17; journey J05). The model's output is
simulated here; the backend rules decide. Fictional catalogue and texts only."""

from __future__ import annotations

import pytest

from app.identity.aliases import collision_check, record_proposals
from app.identity.catalogue import load_identities
from app.identity.intake import store_text_source
from app.identity.matching import match_text
from app.identity.queries import build_query_plan
from app.identity.service import identify_source

from .conftest import sign_in


def add_source(db, contracts, settings, text, focus, native_id):
    source = store_text_source(
        db,
        connector_id="firecrawl",
        native_id=native_id,
        canonical_url=f"https://forum.example.test/{native_id}",
        source_kind="forum_post",
        text=text,
        policy_family="web_public_pages",
    )
    identify_source(db.client, db, contracts, source, focus_project_ids=focus)
    link = db["ai_project_source_links"].find_one({"source.id": source["id"], "project_id": focus[0]})
    return db["ai_evidence"].find_one({"link_id": link["_id"]})


def identity_of(db, project_id):
    identities = load_identities(db)
    return next(i for i in identities if i.id == project_id), [i for i in identities if i.id != project_id]


def propose(db, settings, project_id, proposals, evidence_docs):
    identity, others = identity_of(db, project_id)
    allowed = {e["id"]: e for e in evidence_docs}
    return record_proposals(db, identity, others, proposals, allowed, "tsk_01K0000000000000000000000A")


def proposal(alias, evidence_ids, *, target=None, kind="rera_id", alias_type="short_name"):
    return {
        "alias_text": alias,
        "alias_type": alias_type,
        "target_rera_id": target,
        "evidence_ids": evidence_ids,
        "strong_identifier_kind": kind,
        "strong_identifier_evidence_id": evidence_ids[0] if evidence_ids else "",
    }


@pytest.fixture
def zc(db, contracts, settings, fictional):
    """Evidence where 'ZC West' appears with Zephyrine Crest West's RERA ID."""
    z = fictional["Zephyrine Crest"]
    text = "Zephyrine Crest West (TST/905/805/2024/15), which everyone calls ZC West, has a new lobby."
    return z, add_source(db, contracts, settings, text, [z], "zc-1")


def test_a_proposal_with_a_strong_identifier_is_recorded(db, settings, contracts, zc):
    z, evidence = zc
    [row] = propose(db, settings, z, [proposal("ZC West", [evidence["id"]], target="TST/905/805/2024/15")], [evidence])
    assert row["outcome"] == "proposed"
    doc = db["ai_alias_proposals"].find_one({"_id": row["proposal_id"]})
    assert doc["strong_identifier"]["kind"] == "rera_id" and doc["target"] == {
        "kind": "phase",
        "rera_id": "TST/905/805/2024/15",
    }
    assert doc["collision"]["status"] == "none" and doc["status"] == "proposed" and doc["decision"] is None
    from app.identity.aliases import proposal_view

    assert contracts.errors(proposal_view(doc), "catalogue.schema.json#/$defs/AliasProposal") == []


def test_valid_model_output_without_a_strong_identifier_is_rejected(db, contracts, settings, fictional):
    q = fictional["Quillon Residences"]
    evidence = add_source(
        db, contracts, settings, "Quillon by Brightwell Estates, locals call it QR Towers.", [q], "q-1"
    )
    [row] = propose(
        db, settings, q, [proposal("QR Towers", [evidence["id"]], kind="developer_and_locality")], [evidence]
    )
    assert row["outcome"] == "rejected" and "strong identifier" in row["reason"]
    assert db["ai_alias_proposals"].count_documents({}) == 0


def test_evidence_outside_the_task_or_without_the_alias_is_refused(db, settings, zc):
    z, evidence = zc
    outside = propose(db, settings, z, [proposal("ZC West", ["evd_01K0000000000000000000000Z"])], [evidence])
    missing = propose(db, settings, z, [proposal("Zephy Towers", [evidence["id"]])], [evidence])
    mixed = propose(
        db, settings, z, [proposal("ZC West", [evidence["id"], "evd_01K0000000000000000000000Z"])], [evidence]
    )
    assert outside[0]["reason"] == "cites evidence outside the task input"
    assert mixed[0]["reason"] == "cites evidence outside the task input", "one foreign citation is enough to refuse"
    assert missing[0]["reason"] == "the alias does not appear in the cited evidence"


def test_duplicates_merge_and_count_independent_origins(db, contracts, settings, zc):
    z, first = zc
    text = "Visited ZC West at Zephyrine Crest in Sector 65 yesterday."
    second = add_source(db, contracts, settings, text, [z], "zc-2")
    propose(db, settings, z, [proposal("ZC West", [first["id"]])], [first])
    [row] = propose(db, settings, z, [proposal("zc  west", [second["id"]])], [second])
    assert row["outcome"] == "merged"
    doc = db["ai_alias_proposals"].find_one({})
    assert len(doc["evidence_refs"]) == 2 and doc["independent_origin_count"] == 2 and doc["version"] == 2


def test_an_already_approved_name_is_not_proposed_again(db, contracts, settings, fictional):
    q = fictional["Quillon Residences"]
    evidence = add_source(db, contracts, settings, "Quillon Residences (Quillon) in Sector 102.", [q], "q-2")
    [row] = propose(db, settings, q, [proposal("Quillon", [evidence["id"]])], [evidence])
    assert row["outcome"] == "skipped" and row["reason"] == "already an approved alias"


def test_collision_check_is_deterministic(db, fictional):
    q, _ = identity_of(db, fictional["Quillon Residences"])
    _, others = identity_of(db, fictional["Quillon Residences"])
    assert collision_check("tavira", q, others)["status"] == "colliding"
    assert collision_check("tavira", q, others)["colliding_project_ids"] == [fictional["Tavira Vista"]]
    parq = collision_check("parq towers", q, others)  # contains Verdalia Parq's registered name "Parq"
    assert parq["status"] == "colliding" and parq["colliding_project_ids"] == [fictional["Verdalia Parq"]]
    assert collision_check("west towers", q, others)["status"] == "generic"
    assert collision_check("brightwell estates", q, others)["status"] == "generic"
    assert collision_check("sector 102", q, others)["status"] == "generic"
    assert collision_check("qr", q, others)["status"] == "generic"
    assert collision_check("quillon lakeside", q, others) == {
        "status": "none",
        "colliding_project_ids": [],
        "reason": None,
    }


def test_a_proposal_changes_no_query_or_match_until_approved(api, db, contracts, settings, zc, make_user):
    z, evidence = zc
    [row] = propose(db, settings, z, [proposal("ZC West", [evidence["id"]], target="TST/905/805/2024/15")], [evidence])
    connectors = {"brave_search": {"expected_capabilities": {"search": True}}}
    text = "ZC West lift lobby is finished, TST not mentioned."

    def plan_texts():
        return [q["query_text"] for q in build_query_plan(db, z, connectors)["plan"]["queries"]]

    assert not any("ZC West" in t for t in plan_texts())
    assert not [o for o in match_text(load_identities(db), text) if o.project_id == z]
    headers = sign_in(api, make_user, ["researcher"])
    body = {"action": "approve", "mode": "standalone", "reason": None, "expected_version": 1}
    response = api.post(f"/v1/alias-proposals/{row['proposal_id']}/decisions", json=body, headers=headers)
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "approved" and response.json()["decision"]["mode"] == "standalone"
    config = db["ai_project_configs"].find_one({"_id": z})
    alias = next(a for a in config["aliases"] if a["origin"] == "approved_proposal")
    assert alias["proposal_id"] == row["proposal_id"] and alias["target"]["rera_id"] == "TST/905/805/2024/15"
    assert any("ZC West" in t for t in plan_texts())
    [matched] = [o for o in match_text(load_identities(db), text) if o.project_id == z]
    assert matched.matched_alias == "ZC West" and matched.phase["rera_id"] == "TST/905/805/2024/15"


def test_generic_names_can_only_be_approved_as_context_required(api, db, contracts, settings, fictional, make_user):
    v = fictional["Verdalia Parq"]
    evidence = add_source(db, contracts, settings, "Verdalia Parq (Parq Towers) in Sector 90, Gurgaon.", [v], "v-1")
    [row] = propose(db, settings, v, [proposal("Parq Towers", [evidence["id"]])], [evidence])
    assert db["ai_alias_proposals"].find_one({})["collision"]["status"] == "generic"
    headers = sign_in(api, make_user, ["moderator"])
    url = f"/v1/alias-proposals/{row['proposal_id']}/decisions"
    refused = api.post(
        url, json={"action": "approve", "mode": "standalone", "reason": None, "expected_version": 1}, headers=headers
    )
    assert refused.status_code == 422
    ok = api.post(
        url,
        json={"action": "approve", "mode": "context_required", "reason": None, "expected_version": 1},
        headers=headers,
    )
    assert ok.status_code == 200 and ok.json()["decision"]["mode"] == "context_required"


def test_revoking_sends_the_matches_it_produced_back_to_review(api, db, contracts, settings, zc, make_user):
    z, evidence = zc
    [row] = propose(db, settings, z, [proposal("ZC West", [evidence["id"]], target="TST/905/805/2024/15")], [evidence])
    headers = sign_in(api, make_user, ["researcher", "moderator"])
    url = f"/v1/alias-proposals/{row['proposal_id']}/decisions"
    assert (
        api.post(
            url,
            json={"action": "approve", "mode": "standalone", "reason": None, "expected_version": 1},
            headers=headers,
        ).status_code
        == 200
    )
    # A new post matched only through the approved alias, with the developer and sector: auto-accepted.
    add_source(db, contracts, settings, "ZC West by Orbitas Realty, Sector 65: handover next year.", [z], "zc-3")
    produced = db["ai_project_source_links"].find_one({"match.matched_alias": "ZC West"})
    assert produced["status"] == "auto_accepted"
    revoke = {"action": "revoke", "mode": None, "reason": "Also used for an unrelated tower", "expected_version": 2}
    response = api.post(url, json=revoke, headers=headers)
    assert response.status_code == 200 and response.json()["status"] == "revoked"
    assert db["ai_project_source_links"].find_one({"_id": produced["_id"]})["status"] == "needs_review"
    assert (
        db["ai_jobs"].count_documents({"kind": "invalidate_dependencies", "logical_key": {"$regex": produced["_id"]}})
        == 1
    )
    config = db["ai_project_configs"].find_one({"_id": z})
    assert not any(a["origin"] == "approved_proposal" for a in config["aliases"])
    again = api.post(url, json={**revoke, "expected_version": 3}, headers=headers)
    assert again.status_code == 409 and again.json()["error"]["code"] == "invalid_transition"


def test_list_decide_roles_versions_and_reasons(api, db, contracts, settings, zc, make_user):
    z, evidence = zc
    [row] = propose(db, settings, z, [proposal("ZC West", [evidence["id"]])], [evidence])
    analyst = sign_in(api, make_user, ["analyst"])
    page = api.get(f"/v1/projects/{z}/alias-proposals?status=proposed", headers=analyst)
    assert page.status_code == 200 and [p["id"] for p in page.json()["items"]] == [row["proposal_id"]]
    assert contracts.errors(page.json(), "api.schema.json#/$defs/AliasProposalPage") == []
    url = f"/v1/alias-proposals/{row['proposal_id']}/decisions"
    reject = {"action": "reject", "mode": None, "reason": "Not a real name", "expected_version": 1}
    assert api.post(url, json=reject, headers=analyst).status_code == 403
    publisher = sign_in(api, make_user, ["publisher"])
    assert api.post(url, json=reject, headers=publisher).status_code == 403
    moderator = sign_in(api, make_user, ["moderator"])
    assert api.post(url, json={**reject, "reason": None}, headers=moderator).status_code == 422
    assert api.post(url, json={**reject, "expected_version": 7}, headers=moderator).status_code == 409
    rejected = api.post(url, json=reject, headers=moderator)
    assert rejected.status_code == 200 and rejected.json()["status"] == "rejected"
    assert rejected.json()["decision"]["mode"] is None
    connectors = {"brave_search": {"expected_capabilities": {"search": True}}}
    assert "ZC West" in build_query_plan(db, z, connectors)["plan"]["queries"][0]["exclusions"]
    assert api.get("/v1/projects/prj_01K0000000000000000000000Z/alias-proposals", headers=analyst).status_code == 404
