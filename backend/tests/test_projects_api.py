"""UC-26: catalogue import and configuration through the API, and the construction-status seed (Step 04.1,
D19, D27, I16; journeys J01, J18)."""

from __future__ import annotations

import copy
import json

import pytest

from app.config import REPO_ROOT
from app.seed.projects import SeedError, seed_projects, seed_status_records

from .conftest import FICTIONAL_CATALOGUE, sign_in

REAL_INPUT = REPO_ROOT / "contracts" / "five-project-input-template.json"
STATUS_FILE = REPO_ROOT / "seed" / "construction_status.json"


def fictional_input():
    return json.loads(FICTIONAL_CATALOGUE.read_text(encoding="utf-8"))


def test_import_needs_an_idempotency_key_and_replays_the_same_result(api, db, make_user, contracts):
    headers = sign_in(api, make_user, ["researcher"])
    body = fictional_input()
    missing = api.post("/v1/projects/import", json=body, headers=headers)
    assert missing.status_code == 422 and missing.json()["error"]["fields"][0]["path"] == "Idempotency-Key"
    first = api.post("/v1/projects/import", json=body, headers={**headers, "Idempotency-Key": "import-0001"})
    assert first.status_code == 200 and contracts.errors(first.json(), "api.schema.json#/$defs/ImportResult") == []
    assert [p["created"] for p in first.json()["projects"]] == [True] * 5
    replay = api.post("/v1/projects/import", json=body, headers={**headers, "Idempotency-Key": "import-0001"})
    assert replay.json() == first.json(), "same key and body return the original result"
    fresh = api.post("/v1/projects/import", json=body, headers={**headers, "Idempotency-Key": "import-0002"})
    assert [p["created"] for p in fresh.json()["projects"]] == [False] * 5, "a new key re-imports without duplicates"
    assert db["projects"].count_documents({}) == 5
    changed = copy.deepcopy(body)
    changed["projects"][0]["locality"] = "Sector 103"
    conflict = api.post("/v1/projects/import", json=changed, headers={**headers, "Idempotency-Key": "import-0001"})
    assert conflict.status_code == 409 and conflict.json()["error"]["code"] == "idempotency_conflict"


def test_import_roles_and_contract_validation(api, make_user):
    analyst = sign_in(api, make_user, ["analyst"])
    assert (
        api.post(
            "/v1/projects/import", json=fictional_input(), headers={**analyst, "Idempotency-Key": "k-000001"}
        ).status_code
        == 403
    )
    researcher = sign_in(api, make_user, ["researcher"])
    bad = fictional_input()
    bad["projects"] = bad["projects"][:4]
    response = api.post("/v1/projects/import", json=bad, headers={**researcher, "Idempotency-Key": "k-000002"})
    assert response.status_code == 422 and response.json()["error"]["code"] == "validation_failed"


def test_optional_fields_do_not_block_onboarding(api, db, make_user):
    body = fictional_input()
    for item in body["projects"]:
        item.update(micromarket=None, developer=None, rera_ids=[], alternate_names=[])
    headers = sign_in(api, make_user, ["admin"])
    response = api.post("/v1/projects/import", json=body, headers={**headers, "Idempotency-Key": "k-000003"})
    assert response.status_code == 200 and db["projects"].count_documents({"developer": None}) == 5


def test_list_and_get_projects_match_the_contract(api, db, make_user, contracts, fictional):
    headers = sign_in(api, make_user, ["analyst"])
    page = api.get("/v1/projects?limit=2", headers=headers)
    assert page.status_code == 200 and contracts.errors(page.json(), "api.schema.json#/$defs/ProjectPage") == []
    ids = [p["project"]["id"] for p in page.json()["items"]]
    rest = api.get(f"/v1/projects?limit=10&cursor={page.json()['next_cursor']}", headers=headers).json()
    ids += [p["project"]["id"] for p in rest["items"]]
    assert sorted(ids) == sorted(fictional.values()) and rest["next_cursor"] is None
    detail = api.get(f"/v1/projects/{fictional['Quillon Residences']}", headers=headers)
    assert detail.status_code == 200 and contracts.errors(detail.json(), "api.schema.json#/$defs/ProjectDetail") == []
    assert "match_key" not in detail.json()["project"]
    assert api.get("/v1/projects/prj_01K0000000000000000000000Z", headers=headers).status_code == 404
    assert api.get("/v1/projects/not-a-project", headers=headers).status_code == 404


def test_config_changes_need_the_expected_version(api, db, make_user, contracts, fictional):
    q = fictional["Quillon Residences"]
    headers = sign_in(api, make_user, ["researcher"])
    version = db["ai_project_configs"].find_one({"_id": q})["version"]
    status = [
        {
            "status": "under_construction",
            "applies_to": {"kind": "phase", "rera_id": "TST/902/802/2024/12"},
            "basis": "rera_registry",
            "as_of": "2026-09-28",
            "note": "fictional test record",
        }
    ]
    body = {"expected_version": version, "negative_keywords": ["quillon pune"], "construction_status": status}
    response = api.patch(f"/v1/projects/{q}", json=body, headers=headers)
    assert (
        response.status_code == 200
        and contracts.errors(response.json(), "catalogue.schema.json#/$defs/ProjectConfig") == []
    )
    assert response.json()["version"] == version + 1 and response.json()["updated_by"]["role"] == "researcher"
    stale = api.patch(f"/v1/projects/{q}", json=body, headers=headers)
    assert stale.status_code == 409 and stale.json()["error"]["current_version"] == version + 1
    wrong = {
        **body,
        "expected_version": version + 1,
        "construction_status": [{**status[0], "applies_to": {"kind": "phase", "rera_id": "TST/903/803/2024/13"}}],
    }
    assert api.patch(f"/v1/projects/{q}", json=wrong, headers=headers).status_code == 422
    unknown = {"expected_version": version + 1, "sources": [{"connector_id": "made_up", "enabled": True}]}
    assert api.patch(f"/v1/projects/{q}", json=unknown, headers=headers).status_code == 422
    aliases = {"expected_version": version + 1, "aliases": []}
    assert api.patch(f"/v1/projects/{q}", json=aliases, headers=headers).status_code == 422, (
        "aliases change by decision only"
    )
    moderator = sign_in(api, make_user, ["moderator"])
    assert (
        api.patch(f"/v1/projects/{q}", json={**body, "expected_version": version + 1}, headers=moderator).status_code
        == 403
    )


def test_real_catalogue_gets_the_recorded_phase_statuses(db, contracts, settings):
    seed_projects(db.client, db, contracts, REAL_INPUT, settings.seed_dir)
    first = seed_status_records(db.client, db, contracts, STATUS_FILE)
    assert [r["outcome"] for r in first] == ["added"] * 7
    again = seed_status_records(db.client, db, contracts, STATUS_FILE)
    assert [r["outcome"] for r in again] == ["unchanged"] * 7, "seeding statuses is idempotent"
    antalya = db["projects"].find_one({"slug": "m3m-antalya-hills-sector-79-gurgaon"})
    records = db["ai_project_configs"].find_one({"_id": antalya["_id"]})["construction_status"]
    by_target = {r["applies_to"]["rera_id"]: r["status"] for r in records}
    assert by_target["GGM/650/382/2022/125"] == "ready_to_move"
    assert "GGM/833/565/2024/60" not in by_target, "Phase II stays unknown until confirmed (I16)"
    assert by_target[None] == "partially_ready"
    import contract_tools

    assert contract_tools.consistency_flags("resident_experience", records, "GGM/833/565/2024/60", "2026-09-28") == [
        "status_unknown"
    ]
    assert contract_tools.consistency_flags("resident_experience", records, "GGM/650/382/2022/125", "2026-09-28") == []
    privana = db["projects"].find_one({"slug": "dlf-privana-sector-76-gurgaon"})
    dlf = db["ai_project_configs"].find_one({"_id": privana["_id"]})["construction_status"]
    assert contract_tools.consistency_flags("resident_experience", dlf, "GGM/819/551/2024/46", "2026-09-29") == [
        "occupancy_before_possession"
    ]


def test_status_records_must_name_the_projects_own_registrations(db, contracts, settings, tmp_path):
    seed_projects(db.client, db, contracts, REAL_INPUT, settings.seed_dir)
    data = json.loads(STATUS_FILE.read_text(encoding="utf-8"))
    data["records"] = [{**data["records"][1], "applies_to": {"kind": "phase", "rera_id": "GGM/650/382/2022/125"}}]
    bad = tmp_path / "status.json"
    bad.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(SeedError, match="not one of its RERA registrations"):
        seed_status_records(db.client, db, contracts, bad)
