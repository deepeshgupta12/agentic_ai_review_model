"""UC-35 Brave discovery, UC-36 the web reader, UC-37 YouTube (Step 05.1-05.5). A fake internet only."""

from __future__ import annotations

from datetime import UTC, datetime
from urllib.parse import parse_qs

import pytest

from app.connectors.base import ProviderError, QuotaExhausted
from app.connectors.brave import BraveSearch
from app.connectors.web import WebFetch
from app.connectors.youtube import YouTubeDataApi, duration_ms
from app.sources.robots import RobotsCache

from .fakenet import FakeNet, article

NOW = datetime(2026, 9, 29, 12, 0, tzinfo=UTC)
QUERY = {
    "connector_id": "brave_search",
    "query_text": "Quillon Residences Gurgaon",
    "window_days": 90,
    "language": "en",
    "exclusions": ["quillon pune"],
    "priority": "high",
    "purpose": "project_name",
}


def brave_answer(results, more=False, status=200):
    body = {
        "query": {"original": "q", "more_results_available": more},
        "web": {
            "results": [
                {"url": u, "title": f"Title {i}", "page_age": "2026-08-01T00:00:00", "language": "en"}
                for i, u in enumerate(results)
            ]
        },
    }
    return lambda request: (status, body if status == 200 else {"error": "denied"})


def brave(net, db, settings, **overrides):
    for k, v in overrides.items():
        setattr(settings, k, v)
    return BraveSearch("test-only-brave-key-0000", net.client(), db, settings, now=lambda: NOW)


def test_brave_returns_metadata_only_hits_and_pages_by_offset(db, settings):
    net = FakeNet()
    net.json(
        "api.search.brave.com", brave_answer(["https://Forum.Example.test/t/1?utm_source=x", "ftp://bad/x"], more=True)
    )
    connector = brave(net, db, settings, brave_pages_per_query=2)
    page = connector.discover(QUERY, None)
    assert [i.native_id for i in page.items] == ["https://forum.example.test/t/1"]
    item = page.items[0]
    assert item.capture_level == "metadata_only" and item.text is None and item.source_kind == "search_result"
    assert item.publication_date["status"] == "approximate" and item.publication_date["basis"] == "platform_metadata"
    assert page.next_cursor == "1"
    request = net.requests[0]
    params = parse_qs(request.url.query.decode())
    assert request.headers["X-Subscription-Token"] == "test-only-brave-key-0000"
    assert params["q"] == ['Quillon Residences Gurgaon -"quillon pune"'] and params["offset"] == ["0"]
    assert params["freshness"] == ["2026-07-01to2026-09-29"] and params["count"] == ["20"]
    assert connector.discover(QUERY, "1").next_cursor is None, "stops at the configured page budget"


def test_brave_refusal_and_quota_are_explicit(db, settings):
    net = FakeNet()
    net.json("api.search.brave.com", brave_answer([], status=401))
    with pytest.raises(ProviderError) as info:
        brave(net, db, settings).discover(QUERY, None)
    assert info.value.code == "access_refused" and not info.value.retryable
    empty = FakeNet()
    empty.json("api.search.brave.com", brave_answer([]))
    with pytest.raises(QuotaExhausted):
        brave(empty, db, settings, brave_monthly_queries=0).discover(QUERY, None)
    assert empty.requests == [], "no request is made without quota"


@pytest.fixture
def web_policy(db, contracts, api, make_user):
    """Allow-list the fictional forum host through the admin API (a recorded decision)."""
    from app.sources.policies import current

    from .conftest import sign_in
    from .test_policies import version_request

    web = current(db, "web_public_pages")
    body = version_request(
        "web_public_pages",
        hosts=[*web["hosts"], "forum.example.test"],
        excluded_hosts=web["excluded_hosts"],
        conditions=web["conditions"],
        basis="test allow-list",
    )
    assert (
        api.post(
            "/v1/admin/source-policies",
            json=body,
            headers={**sign_in(api, make_user, ["admin"]), "Idempotency-Key": "policy-version-0001"},
        ).status_code
        == 201
    )


def reader(net, db):
    client = net.client()
    return WebFetch(client, RobotsCache(client, "ProjectIntelligenceBot"), db)


def test_the_web_reader_reads_an_allowed_page_and_logs_the_decision(db, web_policy):
    net = FakeNet()
    net.html(
        "forum.example.test",
        {"/t/1": (200, article("Tower C update", "Quillon Residences in Sector 102 reached the 20th floor. " * 6))},
    )
    outcome = reader(net, db).fetch("https://forum.example.test/t/1")
    assert outcome.status == "fetched" and outcome.item is not None
    assert outcome.item.title == "Tower C update" and "20th floor" in outcome.item.text
    assert outcome.item.publication_date == {
        "status": "approximate",
        "value": "2026-08-14T00:00:00Z",
        "precision": "day",
        "basis": "page_markup",
    }
    assert outcome.item.language == "en" and outcome.item.author["display_name"] == "A Writer"
    log = db["ai_fetch_log"].find_one({"url": "https://forum.example.test/t/1"})
    assert log["outcome"] == "fetched" and log["family"] == "web_public_pages" and log["robots"] == "parsed"


def test_a_date_written_only_in_the_text_stays_unknown():
    from app.connectors.web import extract, publication_date

    body = "<p>" + "Quillon Residences in Sector 102 has large balconies. " * 8 + "</p>"
    free_text = f"<html><body><article>{body}<p>Updated on 29 September 2026.</p></article></body></html>"
    assert publication_date(extract(free_text, "https://forum.example.test/a")["date"])["status"] == "unknown"
    marked = free_text.replace(
        "<html>", '<html><head><meta property="article:published_time" content="2026-08-14T09:30"></head>'
    )
    assert publication_date(extract(marked, "https://forum.example.test/a")["date"])["value"] == "2026-08-14T00:00:00Z"


def test_the_web_reader_never_requests_a_page_the_policy_does_not_allow(db):
    net = FakeNet()
    net.html("forum.example.test", {"/t/1": (200, article("x", "y"))})
    web = reader(net, db)
    assert web.fetch("https://client-site.example/t/1").status == "not_allowed", "an excluded host (own content)"
    assert web.fetch("https://www.reddit.com/r/x/1").status == "not_allowed"
    assert web.fetch("https://www.youtube.com/watch?v=abc").status == "not_allowed", "YouTube has its own connector"
    assert net.requests == [], "nothing was requested"


def test_robots_refusal_and_http_outcomes(db, web_policy):
    net = FakeNet()
    text = "Quillon Residences in Sector 102 update. " * 10
    net.html(
        "forum.example.test",
        {
            "/ok": (200, article("t", text)),
            "/gone": (410, ""),
            "/blocked": (403, ""),
            "/thin": (200, "<html><body>Loading...</body></html>"),
            "/private/x": (200, article("t", text)),
        },
        robots="User-agent: *\nDisallow: /private\n",
    )
    web = reader(net, db)
    assert web.fetch("https://forum.example.test/private/x").status == "robots_disallowed"
    assert web.fetch("https://forum.example.test/gone").status == "gone"
    blocked = web.fetch("https://forum.example.test/blocked")
    assert blocked.status == "refused" and "not worked around" in blocked.reason
    assert web.fetch("https://forum.example.test/thin").status == "thin"
    assert "/private/x" not in [r.url.path for r in net.requests], "a disallowed path is never requested"


def test_a_redirect_to_a_host_the_policy_does_not_allow_is_stopped(db, web_policy):
    import httpx

    net = FakeNet()
    net.route(
        "forum.example.test",
        lambda r: (
            httpx.Response(200, headers={"content-type": "text/plain"}, text="")
            if r.url.path == "/robots.txt"
            else httpx.Response(302, headers={"location": "https://evil.example.test/x"})
        ),
    )
    net.html("evil.example.test", {"/x": (200, article("t", "x" * 400))})
    outcome = reader(net, db).fetch("https://forum.example.test/go")
    assert outcome.status == "error" and "redirect" in outcome.reason
    assert "evil.example.test" not in net.hosts_requested()


def test_an_allowed_redirect_is_stored_where_it_landed_and_logged_with_both_addresses(db, web_policy):
    """Found live on 30 Sep 2026: a developer blog redirected, and the fetch log named only the address asked for."""
    import httpx

    net = FakeNet()
    body = article("Tower C update", "Quillon Residences in Sector 102 reached the 20th floor. " * 6)

    def forum(request):
        if request.url.path == "/robots.txt":
            return httpx.Response(200, headers={"content-type": "text/plain"}, text="")
        if request.url.path == "/old-post":
            return httpx.Response(301, headers={"location": "https://forum.example.test/t/1"})
        return httpx.Response(200, headers={"content-type": "text/html"}, text=body)

    net.route("forum.example.test", forum)
    outcome = reader(net, db).fetch("https://forum.example.test/old-post")
    assert outcome.status == "fetched" and outcome.item.native_id == "https://forum.example.test/t/1"
    log = db["ai_fetch_log"].find_one({"url": "https://forum.example.test/old-post"})
    assert log["outcome"] == "fetched" and log["final_url"] == "https://forum.example.test/t/1"


def youtube_net(comments_disabled=False):
    net = FakeNet()

    def answer(request):
        path = request.url.path.rsplit("/", 1)[-1]
        assert request.headers["X-Goog-Api-Key"] == "test-only-youtube-key-0000" and "key=" not in str(request.url)
        if path == "search":
            return 200, {"items": [{"id": {"videoId": "vid1"}}], "nextPageToken": None}
        if path == "videos":
            return 200, {
                "items": [
                    {
                        "id": "vid1",
                        "snippet": {
                            "title": "Quillon Residences Sector 102 site visit",
                            "description": "Walkthrough",
                            "channelId": "chan1",
                            "channelTitle": "Homes Channel",
                            "publishedAt": "2026-08-10T10:00:00Z",
                            "defaultAudioLanguage": "hi",
                        },
                        "contentDetails": {"duration": "PT12M5S"},
                    }
                ]
            }
        if path == "commentThreads":
            if comments_disabled:
                return 403, {"error": {"errors": [{"reason": "commentsDisabled"}]}}
            return 200, {
                "items": [
                    {
                        "snippet": {
                            "topLevelComment": {
                                "id": "c1",
                                "snippet": {
                                    "textDisplay": "Possession is late again",
                                    "authorDisplayName": "Viewer",
                                    "authorChannelId": {"value": "someone"},
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

    net.json("www.googleapis.com", answer)
    return net


def youtube(net, db, settings):
    return YouTubeDataApi("test-only-youtube-key-0000", net.client(), db, settings, now=lambda: NOW)


def test_youtube_videos_are_metadata_only_and_comments_keep_their_thread(db, settings):
    net = youtube_net()
    yt = youtube(net, db, settings)
    page = yt.discover({**QUERY, "connector_id": "youtube_data_api"}, None)
    [video] = page.items
    assert video.capture_level == "metadata_only" and video.text is None and video.source_kind == "video"
    assert video.media["duration_ms"] == 725_000 and video.media["format"] == "unknown"
    assert video.media["access_status"] == "metadata_only" and video.media["transcript_route"] is None
    assert page.match_text[video.native_id].startswith("Quillon Residences Sector 102"), "matching text is not stored"
    parent = {"id": "src_01K0000000000000000000000V", "revision": 1, "native_id": video.native_id, "media": video.media}
    thread = yt.fetch_thread(parent, None)
    top, reply = thread.items
    assert top.parent == {"id": parent["id"], "revision": 1} and top.author["role"] == "unknown"
    assert reply.parent == {"native_id": "comment:c1"}, "a reply belongs to its top comment"
    assert reply.author == {"display_name": "Homes Channel", "role": "creator", "role_basis": "platform_badge"}
    usage = yt.health()
    assert usage["quota"]["used"] == 1 and usage["units"]["used"] == 2, "search and units are separate buckets"


def test_youtube_comments_turned_off_is_a_fact_not_a_failure(db, settings):
    yt = youtube(youtube_net(comments_disabled=True), db, settings)
    with pytest.raises(ProviderError) as info:
        yt.fetch_thread(
            {"id": "src_01K0000000000000000000000V", "revision": 1, "native_id": "video:vid1", "media": None}, None
        )
    assert info.value.code == "comments_disabled" and not info.value.retryable
    assert duration_ms("PT1H2M3S") == 3_723_000 and duration_ms("P1D") == 86_400_000 and duration_ms("") is None


@pytest.fixture
def record_only_policy(db, contracts, api, make_user):
    """The forum allow-listed under a version that records robots.txt without enforcing it (D46)."""
    from app.sources.policies import current

    from .conftest import sign_in
    from .test_policies import version_request

    web = current(db, "web_public_pages")
    body = version_request(
        "web_public_pages",
        hosts=[*web["hosts"], "forum.example.test"],
        excluded_hosts=web["excluded_hosts"],
        conditions=web["conditions"],
        basis="test allow-list, robots.txt recorded only",
        robots_txt="record_only",
    )
    assert (
        api.post(
            "/v1/admin/source-policies",
            json=body,
            headers={**sign_in(api, make_user, ["admin"]), "Idempotency-Key": "policy-version-0002"},
        ).status_code
        == 201
    )


def test_under_record_only_robots_txt_is_logged_but_does_not_block(db, record_only_policy):
    net = FakeNet()
    text = "Quillon Residences in Sector 102 update. " * 10
    net.html(
        "forum.example.test",
        {"/private/x": (200, article("t", text)), "/blocked": (403, "")},
        robots="User-agent: *\nDisallow: /private\n",
    )
    web = reader(net, db)
    assert web.fetch("https://forum.example.test/private/x").status == "fetched"
    log = db["ai_fetch_log"].find_one({"url": "https://forum.example.test/private/x"})
    assert log["outcome"] == "fetched" and log["robots"] == "disallowed (parsed)", "the verdict is kept"
    blocked = web.fetch("https://forum.example.test/blocked")
    assert blocked.status == "refused" and "not worked around" in blocked.reason, "a refused page still is (D33)"


def test_under_record_only_a_refused_robots_txt_does_not_block_either(db, record_only_policy):
    import httpx

    net = FakeNet()
    body = article("Tower C update", "Quillon Residences in Sector 102 reached the 20th floor. " * 6)
    net.route(
        "forum.example.test",
        lambda r: (
            httpx.Response(403, headers={"content-type": "text/html"}, text="challenge")
            if r.url.path == "/robots.txt"
            else httpx.Response(200, headers={"content-type": "text/html"}, text=body)
        ),
    )
    outcome = reader(net, db).fetch("https://forum.example.test/t/1")
    assert outcome.status == "fetched"
    log = db["ai_fetch_log"].find_one({"url": "https://forum.example.test/t/1"})
    assert log["robots"] == "disallowed (robots_refused)"
