"""UC-33: source policies in the database (Step 05.5; D34, D38). Immutable versions, host resolution, eligibility
that follows the current version, and the admin API. Fictional catalogue and texts only."""

from __future__ import annotations

import json

import pytest

from app.config import REPO_ROOT
from app.identity.evidence import usable_for_identity
from app.identity.intake import store_text_source
from app.identity.service import identify_source
from app.sources.policies import PolicyError, current, policy_view, resolve, seed_policies

from .conftest import sign_in

SEED = REPO_ROOT / "seed" / "source_policies.json"


def version_request(family, **changes):
    base = {
        "family": family,
        "collection_allowed": True,
        "ai_processing_allowed": True,
        "quotation_allowed": True,
        "derived_publication_allowed": True,
        "attribution_required": True,
        "retention_days": 90,
        "hosts": [],
        "excluded_hosts": [],
        "conditions": ["test condition"],
        "basis": "test basis",
        "effective_from": "2026-01-01T00:00:00Z",
        "expires_at": None,
    }
    return {**base, **changes}


def test_seeded_policies_are_current_and_match_the_contract(db, contracts):
    families = {p["family"] for p in db["ai_source_policies"].find()}
    assert (
        len(families) == 13
        and {"competitor_portals", "web_public_pages", "instagram_public", "google_alerts"} <= families
    )
    web = current(db, "web_public_pages")
    assert web["policy_version"] == 5 and {"dlf.in", "republicworld.com"} <= set(web["hosts"])
    assert web["robots_txt"] == "record_only", "D46"
    assert "client-site.example" not in web["hosts"], "own content is not independent evidence"
    assert current(db, "competitor_portals")["policy_version"] == 2
    for doc in db["ai_source_policies"].find():
        assert contracts.errors(policy_view(doc), "sources.schema.json#/$defs/SourcePolicy") == [], doc["family"]


def test_a_stored_version_cannot_change(db, contracts, tmp_path):
    again = seed_policies(db.client, db, contracts, SEED)
    assert {r["outcome"] for r in again} == {"unchanged"}
    data = json.loads(SEED.read_text(encoding="utf-8"))
    next(p for p in data["policies"] if p["family"] == "youtube")["retention_days"] = 999
    changed = tmp_path / "policies.json"
    changed.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(PolicyError, match="immutable"):
        seed_policies(db.client, db, contracts, changed)


@pytest.mark.parametrize(
    ("url", "family", "may_collect"),
    [
        ("https://www.youtube.com/watch?v=abc", "youtube", True),
        ("https://old.reddit.com/r/gurgaon/comments/1", "reddit", False),
        ("https://www.quora.com/What-about-it", "quora", False),
        ("https://m.facebook.com/groups/1", "meta", False),
        ("https://www.nobroker.in/some-project", "competitor_portals", True),
        ("https://www.99acres.com/some-project", "competitor_portals", True),
        ("https://haryanarera.gov.in/view_project/1", "official_records", True),
        ("https://forum.example.test/thread/1", "web_public_pages", False),
        ("https://www.dlf.in/privana", "web_public_pages", True),
        ("https://client-site.example/some-project", "web_public_pages", False),
    ],
)
def test_the_host_decides_the_family(db, url, family, may_collect):
    got = resolve(db, url)
    assert (got.family, got.may_collect) == (family, may_collect), got.reason


def test_a_generic_web_host_needs_the_allow_list(api, db, make_user):
    assert "allow-list" in resolve(db, "https://forum.example.test/t/1").reason
    headers = sign_in(api, make_user, ["admin"])
    web = current(db, "web_public_pages")
    body = version_request(
        "web_public_pages",
        hosts=["forum.example.test"],
        excluded_hosts=web["excluded_hosts"],
        conditions=web["conditions"],
        basis="Test: allow-list one fictional forum",
        retention_days=90,
    )
    response = api.post("/v1/admin/source-policies", json=body, headers=headers)
    assert response.status_code == 201, response.text
    assert response.json()["policy_version"] == web["policy_version"] + 1 and response.json()["status"] == "accepted"
    assert resolve(db, "https://forum.example.test/t/1").may_collect
    assert not resolve(db, "https://other.example.test/t/1").may_collect


def test_narrowing_a_policy_applies_at_once_and_is_rechecked(api, db, contracts, make_user, fictional):
    q = fictional["Quillon Residences"]
    source = store_text_source(
        db,
        connector_id="web_fetch",
        native_id="https://nobroker.in/q",
        canonical_url="https://nobroker.in/q",
        source_kind="forum_post",
        text="Visited Quillon Residences in Sector 102.",
        policy_family="competitor_portals",
    )
    identify_source(db.client, db, contracts, source, focus_project_ids=[q])
    evidence = db["ai_evidence"].find_one({})
    assert usable_for_identity(db, evidence)
    headers = sign_in(api, make_user, ["admin"])
    body = version_request(
        "competitor_portals",
        ai_processing_allowed=False,
        derived_publication_allowed=False,
        quotation_allowed=False,
        hosts=current(db, "competitor_portals")["hosts"],
        basis="Test: AI use withdrawn",
    )
    assert api.post("/v1/admin/source-policies", json=body, headers=headers).status_code == 201
    assert not usable_for_identity(db, evidence), "the current version governs stored evidence"
    job = db["ai_jobs"].find_one({"kind": "invalidate_dependencies"})
    assert job is not None and job["logical_key"] == "invalidate_dependencies:policy:competitor_portals:v3"
    audit = db["ai_audit_events"].find_one(
        {"action": "source_policy.created", "details.family": "competitor_portals", "details.policy_version": 3}
    )
    assert "ai_processing_allowed" in audit["details"]["narrowed"]


def test_policy_api_roles_and_the_rights_chain(api, db, make_user, contracts):
    researcher = sign_in(api, make_user, ["researcher"])
    page = api.get("/v1/admin/source-policies?limit=50", headers=researcher)
    assert page.status_code == 200 and contracts.errors(page.json(), "api.schema.json#/$defs/PolicyPage") == []
    assert len(page.json()["items"]) == 14, (
        "every stored version: 11, instagram_public v1 and meta v2 (D54), google_alerts v1"
    )
    assert api.post("/v1/admin/source-policies", json=version_request("youtube"), headers=researcher).status_code == 403
    analyst = sign_in(api, make_user, ["analyst"])
    assert api.get("/v1/admin/source-policies", headers=analyst).status_code == 403
    admin = sign_in(api, make_user, ["admin"])
    before = current(db, "youtube")["policy_version"]
    broken = version_request("youtube", derived_publication_allowed=False)  # quotation needs derived publication
    response = api.post("/v1/admin/source-policies", json=broken, headers=admin)
    assert response.status_code == 422 and response.json()["error"]["code"] == "validation_failed"
    assert current(db, "youtube")["policy_version"] == before, "a refused version is not stored"


def test_robots_txt_handling_is_part_of_each_version(api, db, make_user, contracts):
    """D46: obey unless a version says record_only; versions stored before the field existed read as obey."""
    from .conftest import sign_in

    admin = sign_in(api, make_user, ["admin"])
    seeded = {p["family"]: p for p in api.get("/v1/admin/source-policies?limit=100", headers=admin).json()["items"]}
    assert seeded["web_public_pages"]["robots_txt"] == "record_only" and seeded["youtube"]["robots_txt"] == "obey"
    db["ai_source_policies"].update_one(  # as stored before the field existed; the validator now requires it
        {"family": "reddit"}, {"$unset": {"robots_txt": ""}}, bypass_document_validation=True
    )
    old = next(
        p
        for p in api.get("/v1/admin/source-policies?limit=100", headers=admin).json()["items"]
        if p["family"] == "reddit"
    )
    assert old["robots_txt"] == "obey" and contracts.errors(old, "sources.schema.json#/$defs/SourcePolicy") == []
    made = api.post("/v1/admin/source-policies", json=version_request("quora"), headers=admin)
    assert made.status_code == 201 and made.json()["robots_txt"] == "obey", "omitted means obey"
