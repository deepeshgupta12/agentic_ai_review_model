"""UC-38: collection runs end to end on the replica set with a fake internet (Step 05.2-05.7; journeys J02, J16).
The worker runs the real collect jobs. Fictional catalogue, hosts and texts only."""

from __future__ import annotations

import pytest
from pydantic import SecretStr

from app.connectors import registry
from app.errors import ApiError
from app.identity.links import decide_link
from app.ids import new_id
from app.sources import collection
from app.sources.collection import Collector, cancel_run, start_run
from app.sources.policies import create_version, current
from app.workers.worker import run_one

from .fakenet import FakeNet, article

ADMIN = {"kind": "user", "user_id": "usr_01K00000000000000000000000", "role": "admin"}
RESEARCHER = {"kind": "user", "user_id": "usr_01K00000000000000000000001", "role": "researcher"}
MODERATOR = {"kind": "user", "user_id": "usr_01K00000000000000000000002", "role": "moderator"}
PAGE_TEXT = "Visited Quillon Residences in Sector 102 last weekend. The sample flat was bright but the road is poor. "


def allow_forum(db, contracts):
    web = current(db, "web_public_pages")
    create_version(
        db.client,
        db,
        contracts,
        {
            "family": "web_public_pages",
            "collection_allowed": True,
            "ai_processing_allowed": True,
            "quotation_allowed": True,
            "derived_publication_allowed": True,
            "attribution_required": True,
            "retention_days": 90,
            "hosts": [*web["hosts"], "forum.example.test"],
            "excluded_hosts": web["excluded_hosts"],
            "conditions": web["conditions"],
            "basis": "test allow-list",
            "effective_from": "2026-01-01T00:00:00Z",
            "expires_at": None,
        },
        ADMIN,
    )


def internet(youtube_status=200):
    net = FakeNet()
    net.json(
        "api.search.brave.com",
        lambda r: (
            200,
            {
                "query": {"more_results_available": False},
                "web": {
                    "results": [
                        {"url": "https://forum.example.test/t/1", "title": "Quillon Residences review thread"},
                        {"url": "https://www.reddit.com/r/gurgaon/comments/1", "title": "Reddit thread"},
                        {"url": "https://www.youtube.com/watch?v=vid1", "title": "A video"},
                        {"url": "https://client-site.example/quillon", "title": "Own site"},
                    ]
                },
            },
        ),
    )
    net.html("forum.example.test", {"/t/1": (200, article("Quillon Residences review", PAGE_TEXT * 4))})

    def youtube(request):
        if youtube_status != 200:
            return youtube_status, {"error": {"errors": [{"reason": "backendError"}]}}
        endpoint = request.url.path.rsplit("/", 1)[-1]
        if endpoint == "search":
            return 200, {"items": [{"id": {"videoId": "vid1"}}]}
        if endpoint == "videos":
            return 200, {
                "items": [
                    {
                        "id": "vid1",
                        "snippet": {
                            "title": "Quillon Residences Sector 102 site visit",
                            "description": "A walkthrough.",
                            "channelId": "chan1",
                            "channelTitle": "Homes Channel",
                            "publishedAt": "2026-08-10T10:00:00Z",
                        },
                        "contentDetails": {"duration": "PT9M"},
                    }
                ]
            }
        if endpoint == "commentThreads":
            return 200, {
                "items": [
                    {
                        "snippet": {
                            "topLevelComment": {
                                "id": "c1",
                                "snippet": {
                                    "textDisplay": "Possession is late again",
                                    "authorDisplayName": "Viewer",
                                    "authorChannelId": {"value": "v1"},
                                    "publishedAt": "2026-08-11T10:00:00Z",
                                },
                            }
                        },
                        "replies": {
                            "comments": [
                                {
                                    "id": "c1.r1",
                                    "snippet": {
                                        "textDisplay": "We are told next year",
                                        "authorDisplayName": "Homes Channel",
                                        "authorChannelId": {"value": "chan1"},
                                        "publishedAt": "2026-08-12T10:00:00Z",
                                    },
                                }
                            ]
                        },
                    }
                ]
            }
        return 404, {}

    net.json("www.googleapis.com", youtube)
    return net


@pytest.fixture
def world(db, contracts, settings, fictional, monkeypatch):
    allow_forum(db, contracts)
    settings.brave_search_api_key = SecretStr("test-only-brave-key-0000")
    settings.youtube_api_key = SecretStr("test-only-youtube-key-0000")
    settings.crawler_min_seconds_per_host = 0
    net = internet()
    monkeypatch.setattr(registry, "safe_client", lambda _s: net.client())
    monkeypatch.setattr(collection, "get_settings", lambda: settings)
    return {"net": net, "q": fictional["Quillon Residences"], "fictional": fictional}


def run_all_jobs(db):
    while run_one(db, "test-worker", 60) is not None:
        pass


def start(db, settings, project_id, connectors=None):
    return start_run(db.client, db, settings, project_id, {"window_days": 90, "connectors": connectors}, RESEARCHER)


def coverage(db, run_id):
    return {c["connector_id"]: c for c in db["ai_runs"].find_one({"_id": run_id})["coverage"]}


def test_a_run_collects_every_live_source_and_reports_coverage(db, settings, contracts, world):
    accepted = start(db, settings, world["q"])
    assert contracts.errors(accepted, "api.schema.json#/$defs/Accepted") == []
    run_id = accepted["run_id"]
    assert db["ai_jobs"].count_documents({"run_id": run_id, "kind": "collect"}) == 2
    run_all_jobs(db)
    run = db["ai_runs"].find_one({"_id": run_id})
    from app.sources.collection import run_view

    assert (
        run["stage"] == "analysing"
        and contracts.errors(run_view(run), "operations.schema.json#/$defs/WorkflowRun") == []
    )
    cov = coverage(db, run_id)
    assert cov["brave_search"]["status"] == "complete_for_query" and cov["brave_search"]["attempted_queries"] > 0
    assert (
        "not_collected:reddit" in cov["brave_search"]["note"]
        and "youtube_left_to_youtube_connector" in cov["brave_search"]["note"]
    )
    assert "not_collected:web_public_pages" in cov["brave_search"]["note"], "client-site.example is not on the allow-list"
    assert cov["web_fetch"]["fetched"] == 1 and cov["web_fetch"]["matched"] == 1
    assert cov["youtube_data_api"]["matched"] >= 1 and cov["youtube_data_api"]["metadata_only"] >= 1
    for pending in ("firecrawl", "playwright_fetch"):
        assert cov[pending]["status"] == "access_pending" and cov[pending]["attempted_queries"] == 0
    kinds = {s["source_kind"] for s in db["ai_sources"].find()}
    assert kinds == {"search_result", "article", "video", "comment"}
    assert db["ai_sources"].count_documents({"canonical_url": {"$regex": "reddit|client-site"}}) == 0, (
        "not collected at all"
    )
    assert "www.reddit.com" not in world["net"].hosts_requested()


def test_metadata_never_becomes_evidence_and_links_say_why(db, settings, world):
    run_all_jobs(db) if start(db, settings, world["q"]) else None
    hit = db["ai_sources"].find_one({"source_kind": "search_result"})
    video = db["ai_sources"].find_one({"source_kind": "video"})
    page = db["ai_sources"].find_one({"source_kind": "article"})
    assert db["ai_project_source_links"].count_documents({"source.id": hit["id"]}) == 0, "search hits are not matched"
    video_link = db["ai_project_source_links"].find_one({"source.id": video["id"]})
    assert (
        video_link["status"] == "auto_accepted" and db["ai_evidence"].count_documents({"source.id": video["id"]}) == 0
    )
    page_link = db["ai_project_source_links"].find_one({"source.id": page["id"]})
    assert (
        page_link["status"] == "auto_accepted" and db["ai_evidence"].count_documents({"link_id": page_link["_id"]}) == 1
    )


def test_comments_inherit_their_thread_and_follow_it_back_to_review(db, settings, contracts, world):
    start(db, settings, world["q"])
    run_all_jobs(db)
    video = db["ai_sources"].find_one({"source_kind": "video"})
    top = db["ai_sources"].find_one({"native_id": "comment:c1"})
    reply = db["ai_sources"].find_one({"native_id": "comment:c1.r1"})
    assert top["parent"] == {"id": video["id"], "revision": 1} and reply["parent"] == {"id": top["id"], "revision": 1}
    assert reply["author"]["role"] == "creator" and top["author"]["role"] == "unknown"
    top_link = db["ai_project_source_links"].find_one({"source.id": top["id"]})
    reply_link = db["ai_project_source_links"].find_one({"source.id": reply["id"]})
    assert top_link["status"] == reply_link["status"] == "auto_accepted"
    assert top_link["match"]["signals"] == [] and "inherited" in top_link["match"]["rationale"]
    video_link = db["ai_project_source_links"].find_one({"source.id": video["id"]})
    body = {
        "action": "reject",
        "expected_version": video_link["version"],
        "reason": "Not this project",
        "split_segments": None,
        "remap_project_id": None,
        "phase_rera_id": None,
    }
    decide_link(db.client, db, contracts, video_link["_id"], body, MODERATOR)
    assert db["ai_project_source_links"].find_one({"_id": top_link["_id"]})["status"] == "needs_review"
    assert db["ai_project_source_links"].find_one({"_id": reply_link["_id"]})["status"] == "needs_review", "cascades"


def test_replaying_a_run_creates_no_duplicates(db, settings, world):
    run_id = start(db, settings, world["q"])["run_id"]
    run_all_jobs(db)
    counts = {
        c: db[c].count_documents({}) for c in ("ai_sources", "ai_payloads", "ai_project_source_links", "ai_evidence")
    }
    job = db["ai_jobs"].find_one({"run_id": run_id, "logical_key": {"$regex": ":web$"}})
    Collector(db.client, db, job, lambda: "ok", settings).run_web()
    Collector(
        db.client,
        db,
        db["ai_jobs"].find_one({"run_id": run_id, "logical_key": {"$regex": "youtube"}}),
        lambda: "ok",
        settings,
    ).run_youtube()
    assert {c: db[c].count_documents({}) for c in counts} == counts, "a replayed page stores nothing new"


def test_one_provider_outage_leaves_the_others_complete(db, settings, world, monkeypatch):
    net = internet(youtube_status=500)
    monkeypatch.setattr(registry, "safe_client", lambda _s: net.client())
    run_id = start(db, settings, world["q"])["run_id"]
    run_all_jobs(db)
    cov = coverage(db, run_id)
    assert cov["youtube_data_api"]["status"] == "partial" and "server_error" in cov["youtube_data_api"]["note"]
    assert cov["web_fetch"]["fetched"] == 1 and cov["brave_search"]["status"] == "complete_for_query"
    assert db["ai_runs"].find_one({"_id": run_id})["stage"] == "analysing"


def test_without_credentials_nothing_runs_and_coverage_says_so(db, settings, fictional, contracts, monkeypatch):
    monkeypatch.setattr(collection, "get_settings", lambda: settings)
    assert settings.brave_search_api_key is None and settings.youtube_api_key is None
    run_id = start(db, settings, fictional["Quillon Residences"])["run_id"]
    cov = coverage(db, run_id)
    assert {c["status"] for c in cov.values()} == {"access_pending"}
    assert cov["web_fetch"]["note"].startswith("not run: no discovery source")
    assert db["ai_jobs"].count_documents({"run_id": run_id}) == 0
    assert db["ai_runs"].find_one({"_id": run_id})["stage"] == "analysing", "nothing to collect: the stage moves on"


def test_cancelling_stops_the_jobs_and_keeps_what_was_found(db, settings, contracts, world):
    run_id = start(db, settings, world["q"])["run_id"]
    cancel_run(db.client, db, contracts, run_id, "Wrong window", RESEARCHER)
    assert db["ai_runs"].find_one({"_id": run_id})["stage"] == "cancelled"
    assert run_one(db, "test-worker", 60) is None, "cancelled jobs are not claimed"
    assert db["ai_sources"].count_documents({}) == 0
    with pytest.raises(ApiError) as info:
        cancel_run(db.client, db, contracts, run_id, "again", RESEARCHER)
    assert "cannot be cancelled" in str(info.value)


def test_starting_needs_enabled_connectors(db, settings, world):
    with pytest.raises(ApiError) as info:
        start(db, settings, world["q"], connectors=["reddit_api"])
    assert "not enabled" in str(info.value)
    with pytest.raises(ApiError) as missing:
        start(db, settings, new_id("prj"))
    assert missing.value.status == 404
