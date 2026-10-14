"""UC-38: collection runs end to end on the replica set with a fake internet (Step 05.2-05.7; journeys J02, J16).
The worker runs the real collect jobs. Fictional catalogue, hosts and texts only."""

from __future__ import annotations

from datetime import timedelta

import pytest
from pydantic import SecretStr

from app.connectors import registry
from app.db import utcnow
from app.errors import ApiError
from app.identity.links import decide_link
from app.ids import new_id
from app.sources import collection, recheck
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
            "host_scope": web.get("host_scope", "allow_list"),
            "basis": "test allow-list",
            "effective_from": "2026-01-01T00:00:00Z",
            "expires_at": None,
        },
        ADMIN,
    )


def internet(youtube_status=200, forum_status=200):
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
    net.html("forum.example.test", {"/t/1": (forum_status, article("Quillon Residences review", PAGE_TEXT * 4))})

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
    net.json("api.pullpush.io", pullpush)
    return net


def _reddit(entry_id: str, days_ago: int, **fields):
    created = (utcnow() - timedelta(days=days_ago)).timestamp()
    return {"id": entry_id, "created_utc": created, "subreddit": "gurgaon", "author": "someone", **fields}


def pullpush(request):
    """The PullPush archive (D67): one thread naming the project, with an owner's comment, a deleted comment and the
    subreddit bot; and a comment naming the project in a thread whose post does not. Fictional texts only."""
    kind = request.url.path.rstrip("/").rsplit("/", 1)[-1]
    params = request.url.params
    post = _reddit(
        "p1",
        5,
        title="Quillon Residences Sector 102, owners please share",
        selftext="Thinking of buying in Quillon Residences. How is the construction going?",
        permalink="/r/gurgaon/comments/p1/quillon_residences/",
        num_comments=3,
    )
    other = _reddit(
        "p2", 6, title="Sector 102 projects compared", selftext="", permalink="/r/gurgaon/comments/p2/s102/"
    )
    owner = _reddit(
        "c1",
        4,
        link_id="t3_p1",
        permalink="/r/gurgaon/comments/p1/quillon_residences/c1/",
        body="I booked a flat here last year. The towers are going up on time but the approach road floods.",
    )
    deleted = _reddit("c2", 4, link_id="t3_p1", permalink="/r/gurgaon/comments/p1/x/c2/", body="[deleted]")
    bot = _reddit(
        "c3", 4, link_id="t3_p1", permalink="/r/gurgaon/comments/p1/x/c3/", body="Rules", author="AutoModerator"
    )
    loose = _reddit(
        "c4",
        5,
        link_id="t3_p2",
        permalink="/r/gurgaon/comments/p2/s102/c4/",
        body="Quillon Residences has the better layouts of the two I visited.",
    )
    if kind == "submission":
        if params.get("ids") == "p2":
            return 200, {"data": [other]}
        return 200, {"data": [post] if "Quillon Residences" in params.get("q", "") else []}
    if kind == "comment":
        if params.get("link_id") == "p1":
            return 200, {"data": [owner, deleted, bot]}
        if params.get("link_id") == "p2":
            return 200, {"data": [loose]}
        return 200, {"data": [loose] if "Quillon Residences" in params.get("q", "") else []}
    return 404, {}


@pytest.fixture
def world(db, contracts, settings, fictional, monkeypatch):
    allow_forum(db, contracts)
    settings.brave_search_api_key = SecretStr("test-only-brave-key-0000")
    settings.youtube_api_key = SecretStr("test-only-youtube-key-0000")
    settings.crawler_min_seconds_per_host = 0
    net = internet()
    monkeypatch.setattr(registry, "safe_client", lambda _s: net.client())
    monkeypatch.setattr(collection, "get_settings", lambda: settings)
    monkeypatch.setattr(recheck, "get_settings", lambda: settings)
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
    assert db["ai_jobs"].count_documents({"run_id": run_id, "kind": "collect"}) == 3  # discovery, youtube, reddit
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
        "reddit_left_to_reddit_connector" in cov["brave_search"]["note"]
        and "youtube_left_to_youtube_connector" in cov["brave_search"]["note"]
    )
    assert "not_collected:web_public_pages" in cov["brave_search"]["note"], "client-site.example is not on the allow-list"
    assert cov["web_fetch"]["fetched"] == 1 and cov["web_fetch"]["matched"] == 1
    assert cov["youtube_data_api"]["matched"] >= 1 and cov["youtube_data_api"]["metadata_only"] >= 1
    assert not {"firecrawl", "playwright_fetch"} & set(cov), "helpers of the web reader are not run sources"
    # Reddit through PullPush (D67): two threads, the owner's comment and the loose one; no deleted or bot comment.
    reddit = cov["reddit_public"]
    assert reddit["status"] == "complete_for_query" and reddit["fetched"] == 4 and reddit["attempted_queries"] > 0
    stored = {s["native_id"]: s for s in db["ai_sources"].find({"connector_id": "reddit_public"})}
    assert set(stored) == {"t3_p1", "t3_p2", "t1_c1", "t1_c4"}
    assert stored["t1_c1"]["parent"] == {"id": stored["t3_p1"]["id"], "revision": 1}
    assert all(s["author"]["display_name"] is None for s in stored.values()), "no username is kept"
    assert stored["t3_p1"]["title"].endswith("(r/gurgaon)")
    status = {
        s["native_id"]: link["status"]
        for s in stored.values()
        for link in db["ai_project_source_links"].find({"source.id": s["id"], "project_id": world["q"]})
    }
    assert status["t3_p1"] == "auto_accepted" and status["t1_c1"] == "auto_accepted", "the comment inherits its post"
    assert status["t1_c4"] == "needs_review", "named without its place: a moderator decides"
    assert status.get("t3_p2", "rejected") == "rejected", "the other thread's post never names the project"
    kinds = {s["source_kind"] for s in db["ai_sources"].find()}
    assert kinds == {"search_result", "article", "video", "comment", "forum_post"}
    assert (
        db["ai_sources"].count_documents({"connector_id": "brave_search", "canonical_url": {"$regex": "reddit"}}) == 0
    )
    assert db["ai_sources"].count_documents({"canonical_url": {"$regex": "client-site"}}) == 0, "not collected at all"
    assert "www.reddit.com" not in world["net"].hosts_requested(), "Reddit itself is never asked (Scrapfly allowance 0)"


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


@pytest.mark.parametrize(
    ("status", "expected", "key"), [(503, "partial", "error_will_retry"), (410, "complete_for_query", "gone")]
)
def test_only_a_page_that_may_read_next_time_leaves_coverage_partial(
    db, settings, world, monkeypatch, status, expected, key
):
    net = internet(forum_status=status)
    monkeypatch.setattr(registry, "safe_client", lambda _s: net.client())
    run_id = start(db, settings, world["q"])["run_id"]
    run_all_jobs(db)
    web = coverage(db, run_id)["web_fetch"]
    assert web["status"] == expected and f"{key}: 1" in web["note"] and web["fetched"] == 0


def test_a_redirected_page_is_not_read_again_on_the_next_run(db, settings, world, monkeypatch):
    import httpx

    net = internet()
    body = article("Quillon Residences review", PAGE_TEXT * 4)
    net.json(
        "api.search.brave.com",
        lambda r: (200, {"query": {}, "web": {"results": [{"url": "https://forum.example.test/old", "title": "x"}]}}),
    )
    net.route(
        "forum.example.test",
        lambda r: (
            httpx.Response(200, headers={"content-type": "text/plain"}, text="")
            if r.url.path == "/robots.txt"
            else httpx.Response(301, headers={"location": "https://forum.example.test/t/1"})
            if r.url.path == "/old"
            else httpx.Response(200, headers={"content-type": "text/html"}, text=body)
        ),
    )
    monkeypatch.setattr(registry, "safe_client", lambda _s: net.client())
    start(db, settings, world["q"], connectors=["brave_search"])
    run_all_jobs(db)
    second = start(db, settings, world["q"], connectors=["brave_search"])["run_id"]
    run_all_jobs(db)
    assert "already_read: 1" in coverage(db, second)["web_fetch"]["note"]
    assert [r.url.path for r in net.requests].count("/old") == 1, "read once, where it landed"


def test_without_credentials_only_the_keyless_reader_runs_and_coverage_says_so(
    db, settings, fictional, contracts, monkeypatch
):
    monkeypatch.setattr(collection, "get_settings", lambda: settings)
    assert settings.brave_search_api_key is None and settings.youtube_api_key is None
    run_id = start(db, settings, fictional["Quillon Residences"])["run_id"]
    cov = coverage(db, run_id)
    assert {k: c["status"] for k, c in cov.items() if c["status"] != "access_pending"} == {"reddit_public": "partial"}
    assert cov["web_fetch"]["note"].startswith("not run: no discovery source")
    assert db["ai_jobs"].count_documents({"run_id": run_id, "kind": "collect"}) == 1, "PullPush needs no key (D67)"
    keyed = start(db, settings, fictional["Quillon Residences"], connectors=["brave_search", "youtube_data_api"])
    cov = coverage(db, keyed["run_id"])
    assert {c["status"] for c in cov.values()} == {"access_pending"}
    assert db["ai_jobs"].count_documents({"run_id": keyed["run_id"], "kind": "collect"}) == 0
    assert db["ai_runs"].find_one({"_id": keyed["run_id"]})["stage"] == "analysing", "nothing to collect: moves on"
    assert db["ai_jobs"].count_documents({"run_id": keyed["run_id"], "kind": "analyse"}) == 1, "analysis is queued"


def test_cancelling_stops_the_jobs_and_keeps_what_was_found(db, settings, contracts, world):
    run_id = start(db, settings, world["q"])["run_id"]
    cancel_run(db.client, db, contracts, run_id, "Wrong window", RESEARCHER)
    assert db["ai_runs"].find_one({"_id": run_id})["stage"] == "cancelled"
    assert run_one(db, "test-worker", 60) is None, "cancelled jobs are not claimed"
    assert db["ai_sources"].count_documents({}) == 0
    with pytest.raises(ApiError) as info:
        cancel_run(db.client, db, contracts, run_id, "again", RESEARCHER)
    assert "cannot be cancelled" in str(info.value)


def test_a_connector_the_run_did_not_plan_is_never_called(db, settings, world):
    """Found live on 30 Sep 2026: the web reader ran for a project whose configuration did not enable it."""
    q = world["q"]
    config = db["ai_project_configs"].find_one({"_id": q})
    off = [{**s, "enabled": False} if s["connector_id"] == "web_fetch" else s for s in config["sources"]]
    db["ai_project_configs"].update_one({"_id": q}, {"$set": {"sources": off}})
    run_id = start(db, settings, q)["run_id"]
    run_all_jobs(db)
    assert "web_fetch" not in coverage(db, run_id)
    assert db["ai_sources"].count_documents({"connector_id": "web_fetch"}) == 0
    assert "forum.example.test" not in world["net"].hosts_requested(), "no page was read"
    assert db["ai_sources"].count_documents({"connector_id": "brave_search", "capture_level": "metadata_only"}) > 0
    only_youtube = start(db, settings, q, connectors=["youtube_data_api"])["run_id"]
    before = world["net"].hosts_requested().count("api.search.brave.com")
    run_all_jobs(db)
    assert world["net"].hosts_requested().count("api.search.brave.com") == before, "Brave was not asked"
    assert set(coverage(db, only_youtube)) == {"youtube_data_api"}


def test_the_collection_checks_pass_on_a_run_and_catch_planted_violations(db, settings, world):
    from app.sources.verify import verify_collection

    run_id = start(db, settings, world["q"])["run_id"]
    run_all_jobs(db)
    rows = {r["check"]: r for r in verify_collection(db, settings)}
    assert all(r["ok"] for r in rows.values()), [r for r in rows.values() if not r["ok"]]
    assert rows["every web page has its fetch decision logged"]["looked_at"] == 1
    hit = db["ai_sources"].find_one({"connector_id": "brave_search"})
    page = db["ai_sources"].find_one({"connector_id": "web_fetch"})
    comment = db["ai_sources"].find_one({"source_kind": "comment"})
    db["ai_sources"].update_one({"_id": hit["_id"]}, {"$set": {"payload_ref": {"store": "payload_store", "key": "x"}}})
    db["ai_evidence"].update_one({}, {"$set": {"source": {"id": hit["id"], "revision": hit["revision"]}}})
    db["ai_fetch_log"].delete_many({"url": page["native_id"]})
    db["ai_fetch_log"].insert_one(
        {
            "connector_id": "firecrawl",
            "url": "https://x.test/",
            "host": "x.test",
            "outcome": "fetched",
            "robots": "disallowed (robots.txt)",
            "run_id": run_id,
            "at": utcnow(),
        }
    )
    db["ai_fetch_log"].insert_one(  # the forum later refuses our crawler; the page read before must not be kept
        {
            "connector_id": "web_fetch",
            "url": "https://forum.example.test/t/2",
            "host": "forum.example.test",
            "outcome": "robots_disallowed",
            "robots": "disallowed (robots_refused)",
            "run_id": None,
            "at": utcnow(),
        }
    )
    db["ai_sources"].update_one({"_id": comment["_id"]}, {"$set": {"parent": None}})
    db["ai_connector_state"].update_one({}, {"$set": {"query_key": "q test-only-brave-key-0000"}})
    failed = {r["check"] for r in verify_collection(db, settings) if not r["ok"]}
    assert failed == {
        "metadata-only records hold no text",
        "no evidence comes from a metadata-only record",
        "every web page has its fetch decision logged",
        "nothing was fetched against robots.txt where the policy obeys it",
        "no page kept from a site that refused us, where the policy obeys robots.txt",
        "every comment belongs to a stored parent",
        "every connector a run used is in its coverage",
        "no configured secret is stored in collected records",
    }


def test_starting_needs_enabled_connectors(db, settings, world):
    with pytest.raises(ApiError) as info:
        start(db, settings, world["q"], connectors=["reddit_api"])
    assert "not enabled" in str(info.value)
    with pytest.raises(ApiError) as missing:
        start(db, settings, new_id("prj"))
    assert missing.value.status == 404
