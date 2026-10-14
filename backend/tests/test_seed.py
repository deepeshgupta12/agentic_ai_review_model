"""UC-20: seeding the catalogue and users (Step 03.4 acceptance: project seeding is idempotent)."""

from __future__ import annotations

import pytest

from app.auth.passwords import WeakPasswordError
from app.config import REPO_ROOT
from app.contracts import to_view
from app.seed.projects import seed_projects
from app.seed.users import seed_users, seeded_users

INPUT = REPO_ROOT / "contracts" / "five-project-input-template.json"
SEED = REPO_ROOT / "seed"
EXPECTED_SLUGS = [
    "dlf-privana-sector-76-gurgaon",
    "conscient-parq-sector-80-gurgaon",
    "sobha-crescent-sector-63a-gurgaon",
    "m3m-forestia-west-manesar-sector-9-gurgaon",
    "m3m-antalya-hills-sector-79-gurgaon",
]


def test_seeding_the_real_input_creates_five_projects_with_step_01_slugs(db, contracts):
    report = seed_projects(db.client, db, contracts, INPUT, SEED)
    assert [r["outcome"] for r in report] == ["created"] * 5
    assert [r["slug"] for r in report] == EXPECTED_SLUGS
    assert db["projects"].count_documents({}) == 5


def test_seeding_twice_changes_nothing_and_keeps_ids(db, contracts):
    first = seed_projects(db.client, db, contracts, INPUT, SEED)
    second = seed_projects(db.client, db, contracts, INPUT, SEED)
    assert [r["outcome"] for r in second] == ["unchanged"] * 5
    assert [r["project_id"] for r in first] == [r["project_id"] for r in second]
    assert db["projects"].count_documents({}) == 5 and db["ai_project_configs"].count_documents({}) == 5


def test_seeded_records_match_the_contracts(db, contracts):
    seed_projects(db.client, db, contracts, INPUT, SEED)
    for doc in db["projects"].find():
        view = to_view({k: v for k, v in doc.items() if k != "match_key"})
        assert contracts.errors(view, "catalogue.schema.json#/$defs/Project") == []
    for doc in db["ai_project_configs"].find():
        assert contracts.errors(to_view(doc, id_field=None), "catalogue.schema.json#/$defs/ProjectConfig") == []


def test_config_has_input_aliases_rera_names_and_export_status(db, contracts):
    seed_projects(db.client, db, contracts, INPUT, SEED)
    antalya = db["projects"].find_one({"slug": EXPECTED_SLUGS[4]})
    config = db["ai_project_configs"].find_one({"_id": antalya["_id"]})
    origins = {(a["text"], a["origin"]) for a in config["aliases"]}
    assert ("M3M Antalya Hills", "input_file") in origins
    assert ("M3M Antalya Hills Phase II", "rera_registered_name") in origins
    assert config["construction_status"] == [
        {
            "status": "partially_ready",
            "applies_to": {"kind": "project", "rera_id": None},
            "basis": "client_export",
            "as_of": "2026-09-25",
            "note": None,
        }
    ]
    parq = db["ai_project_configs"].find_one({"_id": db["projects"].find_one({"slug": EXPECTED_SLUGS[1]})["_id"]})
    single_word = next(a for a in parq["aliases"] if a["normalised"] == "parq")
    assert single_word["mode"] == "context_required"


def test_a_changed_input_updates_the_project_but_keeps_its_id_and_slug(db, contracts, tmp_path):
    import json

    first = seed_projects(db.client, db, contracts, INPUT, SEED)
    data = json.loads(INPUT.read_text())
    data["projects"][0]["alternate_names"] = ["Privana"]
    changed = tmp_path / "input.json"
    changed.write_text(json.dumps(data))
    second = seed_projects(db.client, db, contracts, changed, SEED)
    assert second[0]["outcome"] == "updated" and second[0]["project_id"] == first[0]["project_id"]
    assert second[0]["slug"] == first[0]["slug"]
    project = db["projects"].find_one({"_id": first[0]["project_id"]})
    assert project["alternate_names"] == ["Privana"] and project["version"] == 2


def test_a_connector_added_later_joins_existing_configs_without_changing_choices(db, contracts):
    seed_projects(db.client, db, contracts, INPUT, SEED)
    project_id = db["projects"].find_one({"slug": EXPECTED_SLUGS[1]})["_id"]
    config = db["ai_project_configs"].find_one({"_id": project_id})
    older = [s for s in config["sources"] if s["connector_id"] != "web_fetch"]
    older = [{**s, "enabled": False} if s["connector_id"] == "firecrawl" else s for s in older]
    db["ai_project_configs"].update_one({"_id": project_id}, {"$set": {"sources": older}})
    report = seed_projects(db.client, db, contracts, INPUT, SEED)
    after = db["ai_project_configs"].find_one({"_id": project_id})
    sources = {s["connector_id"]: s["enabled"] for s in after["sources"]}
    assert sources["web_fetch"] is True and sources["firecrawl"] is False, "added with its default; choices kept"
    assert after["version"] == config["version"] + 1 and report[1]["outcome"] == "updated"
    assert [r["outcome"] for r in seed_projects(db.client, db, contracts, INPUT, SEED)] == ["unchanged"] * 5


def test_an_invalid_input_file_is_refused(db, contracts, tmp_path):
    import json

    from app.seed.projects import SeedError

    data = json.loads(INPUT.read_text())
    data["projects"][0]["city"] = "<City>"
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps(data))
    with pytest.raises(SeedError):
        seed_projects(db.client, db, contracts, bad, SEED)
    assert db["projects"].count_documents({}) == 0


def test_the_seeded_coordinator_is_read_from_the_defaults():
    users = seeded_users(SEED)
    assert users == [
        {
            "email": "deepesh.gupta@client-site.example",
            "display_name": "Deepesh Gupta",
            "roles": ["admin", "researcher", "moderator", "publisher", "analyst"],
        }
    ]


def test_a_short_password_is_refused(db):
    with pytest.raises(WeakPasswordError):
        seed_users(db, [{"email": "x@example.test", "display_name": "X", "roles": ["admin"]}], "qwerty!12")
    assert db["users"].count_documents({}) == 0


def test_seed_users_stores_only_an_argon2_hash_and_is_idempotent(db, contracts):
    spec = [{"email": "Coordinator@Example.test", "display_name": "C", "roles": ["admin", "moderator"]}]
    first = seed_users(db, spec, "a-strong-password-123")
    user = db["users"].find_one({"email": "coordinator@example.test"})
    assert first[0]["outcome"] == "created" and user["password_hash"].startswith("$argon2id$")
    assert "a-strong-password-123" not in str(user)
    assert contracts.errors(to_view(user), "operations.schema.json#/$defs/User") == []
    assert seed_users(db, spec, None)[0]["outcome"] == "unchanged"


def test_password_changes_only_on_explicit_reset(db, api):
    spec = [{"email": "reset@example.test", "display_name": "R", "roles": ["analyst"]}]
    seed_users(db, spec, "first-password-123")
    seed_users(db, spec, "second-password-456")
    assert (
        api.post("/v1/auth/login", json={"email": "reset@example.test", "password": "first-password-123"}).status_code
        == 200
    )
    seed_users(db, spec, "second-password-456", reset_password=True)
    assert (
        api.post("/v1/auth/login", json={"email": "reset@example.test", "password": "second-password-456"}).status_code
        == 200
    )


def test_a_connector_removed_from_the_registry_leaves_existing_configs(db, contracts):
    """D59: Google Alerts left the registry; configurations that listed it drop it, so the configuration API (which
    refuses unknown connectors) keeps working, and the other choices are kept."""
    seed_projects(db.client, db, contracts, INPUT, SEED)
    project_id = db["projects"].find_one({"slug": EXPECTED_SLUGS[0]})["_id"]
    config = db["ai_project_configs"].find_one({"_id": project_id})
    retired = {"connector_id": "google_alerts", "enabled": True}
    chosen = [{**s, "enabled": False} if s["connector_id"] == "firecrawl" else s for s in config["sources"]]
    db["ai_project_configs"].update_one({"_id": project_id}, {"$set": {"sources": [*chosen, retired]}})
    seed_projects(db.client, db, contracts, INPUT, SEED)
    after = db["ai_project_configs"].find_one({"_id": project_id})
    sources = {s["connector_id"]: s["enabled"] for s in after["sources"]}
    assert "google_alerts" not in sources and sources["firecrawl"] is False


def test_a_source_registered_later_joins_every_existing_project_at_stack_start(db, contracts):
    """D67: projects added before reddit_public was registered get it at the next stack start (db-setup runs
    sync-catalogue), enabled by its default; the choices made in Setup are kept and a repeat changes nothing."""
    from app.seed.projects import sync_registry_sources

    seed_projects(db.client, db, contracts, INPUT, SEED)
    for config in db["ai_project_configs"].find():  # as configured before D67, with one Setup choice made
        older = [
            {**s, "enabled": False} if s["connector_id"] == "firecrawl" else s
            for s in config["sources"]
            if s["connector_id"] != "reddit_public"
        ]
        db["ai_project_configs"].update_one({"_id": config["_id"]}, {"$set": {"sources": older}})
    versions = {c["_id"]: c["version"] for c in db["ai_project_configs"].find()}
    report = sync_registry_sources(db.client, db, SEED)
    assert len(report) == 5 and all(r["added"] == "reddit_public" for r in report)
    for config in db["ai_project_configs"].find():
        sources = {s["connector_id"]: s["enabled"] for s in config["sources"]}
        assert sources["reddit_public"] is True and sources["firecrawl"] is False, "the Setup choice is kept"
        assert config["version"] == versions[config["_id"]] + 1
        assert contracts.errors(to_view(config, id_field=None), "catalogue.schema.json#/$defs/ProjectConfig") == []
    assert db["ai_audit_events"].count_documents({"action": "project.sources_synced"}) == 5
    assert sync_registry_sources(db.client, db, SEED) == [], "a repeat changes nothing"
