"""UC-30: bounded, versioned search queries (Step 04.3). Real catalogue: queries are not chatter."""

from __future__ import annotations

import json

import pytest

from app.config import REPO_ROOT
from app.identity.queries import PROJECT_PAGE_SITES, REVIEW_SITES, build_query_plan
from app.identity.rules import MAX_QUERIES_PER_CONNECTOR, QUERY_RULES_VERSION
from app.seed.projects import seed_projects

REAL_INPUT = REPO_ROOT / "contracts" / "five-project-input-template.json"


@pytest.fixture
def real(db, contracts, settings):
    seed_projects(db.client, db, contracts, REAL_INPUT, settings.seed_dir)
    registry = json.loads((settings.seed_dir / "connectors.json").read_text(encoding="utf-8"))
    return {c["id"]: c for c in registry["connectors"]}


def plan_for(db, slug, connectors):
    project = db["projects"].find_one({"slug": slug})
    return build_query_plan(db, project["_id"], connectors)


def test_plans_fit_the_discovery_plan_contract(db, contracts, real):
    for project in db["projects"].find():
        result = build_query_plan(db, project["_id"], real)
        assert result["rules_version"] == QUERY_RULES_VERSION
        assert contracts.errors(result["plan"], "agents.schema.json#/$defs/DiscoveryPlan") == []


def test_only_enabled_search_connectors_and_a_cap_per_connector(db, real):
    queries = plan_for(db, "m3m-antalya-hills-sector-79-gurgaon", real)["plan"]["queries"]
    connectors = {q["connector_id"] for q in queries}
    assert connectors == {"brave_search", "firecrawl_search", "youtube_data_api"}, (
        "mandatory search connectors (Firecrawl search, D72); optional ones are off"
    )
    for connector in connectors:
        texts = [q["query_text"].casefold() for q in queries if q["connector_id"] == connector]
        sites = [t for t in texts if "site:" in t]
        assert len(texts) - len(sites) <= MAX_QUERIES_PER_CONNECTOR and len(texts) == len(set(texts))
        # The portal and Quora review pages (D68): the search engines only, one query per site on top of the cap;
        # Firecrawl search also takes the portals' project pages (inurl:, D72).
        expected = {"brave_search": len(REVIEW_SITES), "firecrawl_search": len(REVIEW_SITES) + len(PROJECT_PAGE_SITES)}
        assert len(sites) == expected.get(connector, 0)
        assert texts[: len(sites)] == sites, "the review pages are searched first"


def test_reddit_searches_the_names_itself_and_takes_no_planned_query(db, real):
    project = db["projects"].find_one({"slug": "m3m-antalya-hills-sector-79-gurgaon"})
    config = db["ai_project_configs"].find_one({"_id": project["_id"]})
    assert any(s["connector_id"] == "reddit_public" and s["enabled"] for s in config["sources"])
    assert real["reddit_public"]["expected_capabilities"]["search"] is True
    queries = build_query_plan(db, project["_id"], real)["plan"]["queries"]
    assert not [q for q in queries if q["connector_id"] == "reddit_public"]


def test_identifier_queries_let_unknown_names_surface(db, real):
    queries = plan_for(db, "dlf-privana-sector-76-gurgaon", real)["plan"]["queries"]
    identifiers = {q["query_text"] for q in queries if q["purpose"] == "identifier"}
    assert {"GGM/772/504/2023/116", "GGM/819/551/2024/46", "GGM/954/686/2025/57"} <= identifiers
    assert "DLF Sector 76 Gurgaon" in identifiers
    assert all(q["priority"] == "high" for q in queries if q["purpose"] in ("identifier", "project_name"))


def test_context_required_names_are_paired_with_developer_or_locality(db, real):
    queries = plan_for(db, "conscient-parq-sector-80-gurgaon", real)["plan"]["queries"]
    parq = [q["query_text"] for q in queries if q["query_text"].startswith("Parq")]
    assert parq and all(t in ("Parq Conscient", "Parq Sector 80") for t in parq), parq


def test_negative_keywords_become_exclusions(db, real):
    project = db["projects"].find_one({"slug": "sobha-crescent-sector-63a-gurgaon"})
    db["ai_project_configs"].update_one({"_id": project["_id"]}, {"$set": {"negative_keywords": ["crescent bay"]}})
    queries = build_query_plan(db, project["_id"], real)["plan"]["queries"]
    assert queries and all(q["exclusions"] == ["crescent bay"] for q in queries)
