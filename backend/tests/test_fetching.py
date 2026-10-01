"""UC-34: safe fetching and storage foundations (Step 05.4, 05.5; docs/06 rules 1-3). No network: a mock
transport and a fake resolver stand in for the internet."""

from __future__ import annotations

import threading
from datetime import UTC, datetime, timedelta

import httpx
import pytest

from app.sources import quota
from app.sources.http import FetchError, HostPacer, SafeClient, retry_after_seconds
from app.sources.policies import current
from app.sources.robots import RobotsCache
from app.sources.state import get as get_state
from app.sources.state import save as save_state
from app.sources.store import Item, normalise_url, store_item

UA = "ProjectIntelligenceBot/0.1 (test)"
PUBLIC = {"example.test": ["93.184.216.34"], "other.test": ["93.184.216.35"]}


def resolver(table):
    def resolve(host):
        if host not in table:
            raise FetchError("dns_failed", f"{host} did not resolve", retryable=True)
        return table[host]

    return resolve


def client(handler, table=PUBLIC, **kwargs):
    sleeps = []
    c = SafeClient(
        user_agent=UA,
        max_bytes=kwargs.pop("max_bytes", 10_000),
        max_redirects=kwargs.pop("max_redirects", 3),
        timeout=5,
        pacer=HostPacer(0),
        resolver=resolver(table),
        transport=httpx.MockTransport(handler),
        sleep=sleeps.append,
        **kwargs,
    )
    return c, sleeps


def html(body="<html><body>hi</body></html>", status=200, headers=None):
    return httpx.Response(status, headers={"content-type": "text/html; charset=utf-8", **(headers or {})}, text=body)


@pytest.mark.parametrize(
    ("url", "table", "code"),
    [
        ("http://localhost/x", {"localhost": ["127.0.0.1"]}, "address_refused"),
        ("http://metadata.test/latest", {"metadata.test": ["169.254.169.254"]}, "address_refused"),
        ("http://intranet.test/", {"intranet.test": ["10.0.0.5"]}, "address_refused"),
        ("http://v6.test/", {"v6.test": ["::1"]}, "address_refused"),
        ("http://mixed.test/", {"mixed.test": ["93.184.216.34", "192.168.1.2"]}, "address_refused"),
        ("ftp://example.test/file", PUBLIC, "scheme_refused"),
        ("https://example.test:8443/", PUBLIC, "port_refused"),
        ("https://user:secret@example.test/", PUBLIC, "credentials_in_url"),
    ],
)
def test_non_public_targets_and_odd_urls_are_refused(url, table, code):
    c, _ = client(lambda r: html(), table)
    with pytest.raises(FetchError) as info:
        c.get(url)
    assert info.value.code == code


def test_an_honest_user_agent_is_sent():
    seen = {}

    def handler(request):
        seen["ua"] = request.headers["user-agent"]
        return html()

    c, _ = client(handler)
    assert c.get("https://example.test/").status == 200 and seen["ua"] == UA


def test_every_redirect_hop_is_checked_again():
    def handler(request):
        if request.url.host == "example.test":
            return httpx.Response(302, headers={"location": "http://evil.test/steal"})
        return html()

    c, _ = client(handler, {**PUBLIC, "evil.test": ["10.1.1.1"]})
    with pytest.raises(FetchError) as info:
        c.get("https://example.test/start")
    assert info.value.code == "address_refused"
    hops = []
    c2, _ = client(
        lambda r: (
            httpx.Response(302, headers={"location": "https://other.test/next"})
            if r.url.host == "example.test"
            else html()
        )
    )
    response = c2.get("https://example.test/a", check_hop=hops.append)
    assert hops == ["https://example.test/a", "https://other.test/next"] and response.redirects == [
        "https://example.test/a"
    ]


def test_redirect_budget_is_enforced():
    c, _ = client(lambda r: httpx.Response(301, headers={"location": f"https://example.test/{len(str(r.url))}"}))
    with pytest.raises(FetchError) as info:
        c.get("https://example.test/loop")
    assert info.value.code == "too_many_redirects"


def test_size_and_content_type_limits():
    c, _ = client(lambda r: html("x" * 20_000))
    with pytest.raises(FetchError) as info:
        c.get("https://example.test/big")
    assert info.value.code == "too_large"
    c, _ = client(lambda r: httpx.Response(200, headers={"content-type": "application/pdf"}, content=b"%PDF"))
    with pytest.raises(FetchError) as info:
        c.get("https://example.test/file.pdf")
    assert info.value.code == "content_type_refused"


def test_retry_after_is_respected_and_long_waits_give_up():
    calls = []

    def handler(request):
        calls.append(1)
        return httpx.Response(429, headers={"retry-after": "2"}) if len(calls) == 1 else html()

    c, sleeps = client(handler)
    assert c.get("https://example.test/").status == 200 and sleeps == [2.0]
    c, sleeps = client(lambda r: httpx.Response(429, headers={"retry-after": "3600"}))
    with pytest.raises(FetchError) as info:
        c.get("https://example.test/")
    assert info.value.code == "provider_busy" and info.value.retryable and sleeps == []
    c, _ = client(lambda r: httpx.Response(503))
    with pytest.raises(FetchError) as info:
        c.get("https://example.test/")
    assert info.value.code == "server_error" and info.value.retryable
    assert (
        retry_after_seconds("Wed, 21 Oct 2015 07:28:00 GMT", now=datetime(2015, 10, 21, 7, 27, tzinfo=UTC).timestamp())
        == 60
    )


def test_the_host_pacer_spaces_requests():
    now = [100.0]
    waits = []
    pacer = HostPacer(3.0, clock=lambda: now[0], sleep=waits.append)
    pacer.wait("a.test")
    pacer.wait("a.test")
    pacer.wait("b.test")
    assert waits == [3.0]


def robots_client(status, body=""):
    return client(
        lambda r: (
            httpx.Response(status, headers={"content-type": "text/plain"}, text=body)
            if r.url.path == "/robots.txt"
            else html()
        )
    )[0]


def test_robots_rules_are_followed_conservatively():
    rules = "User-agent: *\nDisallow: /private\n\nUser-agent: ProjectIntelligenceBot\nDisallow: /reviews\n"
    robots = RobotsCache(robots_client(200, rules), "ProjectIntelligenceBot")
    assert robots.decide("https://example.test/news/1").allowed
    assert not robots.decide("https://example.test/reviews/1").allowed
    missing = RobotsCache(robots_client(404), "ProjectIntelligenceBot").decide("https://example.test/any")
    assert missing.allowed and missing.basis == "no_robots_file"
    down = RobotsCache(robots_client(503), "ProjectIntelligenceBot").decide("https://example.test/any")
    assert not down.allowed and down.basis == "robots_unreachable"
    gone = RobotsCache(robots_client(410), "ProjectIntelligenceBot").decide("https://example.test/any")
    assert gone.allowed and gone.basis == "no_robots_file"


@pytest.mark.parametrize("status", [401, 403, 451])
def test_a_robots_file_that_refuses_us_means_nothing_is_fetched(status):
    """Found live on 30 Sep 2026: sites behind bot protection answer robots.txt with 403 and a challenge page."""
    decision = RobotsCache(robots_client(status, "<html>challenge</html>"), "ProjectIntelligenceBot").decide(
        "https://example.test/project/1"
    )
    assert not decision.allowed and decision.basis == "robots_refused"
    limited = RobotsCache(robots_client(429), "ProjectIntelligenceBot").decide("https://example.test/project/1")
    assert not limited.allowed, "rate-limited: retried, then nothing is fetched for now"


def test_urls_are_normalised_before_they_become_ids():
    assert normalise_url("HTTPS://Example.TEST:443/a/b/?utm_source=x&b=2&a=1#top") == "https://example.test/a/b?a=1&b=2"
    assert normalise_url("https://example.test") == "https://example.test/"
    assert normalise_url("https://example.test/p?fbclid=abc") == "https://example.test/p"


def test_quota_reservations_are_atomic_and_follow_the_window(db, settings):
    settings.youtube_daily_searches = 10
    now = datetime(2026, 9, 29, 12, 0, tzinfo=UTC)
    results = []
    threads = [
        threading.Thread(
            target=lambda: results.append(quota.reserve(db, settings, "youtube_data_api", "search", 1, now))
        )
        for _ in range(25)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert results.count(True) == 10, "never more than the limit, even with concurrent workers"
    assert not quota.reserve(db, settings, "youtube_data_api", "search", 1, now)
    next_day = now + timedelta(days=1)
    assert quota.reserve(db, settings, "youtube_data_api", "search", 1, next_day), "a new Pacific day is a new window"
    usage = quota.usage(db, settings, "youtube_data_api", "search", now)
    assert usage["used"] == 10 and usage["resets_at"] == datetime(2026, 9, 30, 7, 0, tzinfo=UTC)


def item(text="Quillon Residences review text.", title="Thread", kind="forum_post", capture="full_content"):
    return Item(
        connector_id="web_fetch",
        native_id="https://example.test/t/1",
        canonical_url="https://example.test/t/1",
        source_kind=kind,
        capture_level=capture,
        title=title,
        text=text,
    )


def test_storing_the_same_page_again_makes_no_new_revision(db):
    policy = current(db, "web_public_pages")
    first = store_item(db, item(), policy)
    again = store_item(db, item(), policy)
    assert first.created and not again.created and again.source["_id"] == first.source["_id"]
    assert db["ai_sources"].count_documents({}) == 1 and db["ai_payloads"].count_documents({}) == 1


def test_a_search_hit_found_again_under_another_title_is_the_same_record(db):
    """Found live on 30 Sep 2026: the same address came back from different queries with different titles."""
    policy = current(db, "web_public_pages")
    first = store_item(db, item(text=None, kind="search_result", capture="metadata_only", title="Title A"), policy)
    again = store_item(db, item(text=None, kind="search_result", capture="metadata_only", title="Title B"), policy)
    assert not again.created and again.source["_id"] == first.source["_id"]
    assert db["ai_sources"].count_documents({}) == 1


def test_an_edited_page_becomes_a_new_revision(db):
    policy = current(db, "web_public_pages")
    first = store_item(db, item(), policy)
    edited = store_item(db, item(text="Quillon Residences review text, edited."), policy)
    assert edited.changed and edited.source["revision"] == 2 and edited.source["id"] == first.source["id"]
    assert db["ai_sources"].find_one({"_id": first.source["_id"]})["lifecycle"] == "superseded"


def test_metadata_only_items_carry_no_payload(db):
    policy = current(db, "web_public_pages")
    hit = Item(
        connector_id="brave_search",
        native_id="https://example.test/t/9",
        canonical_url="https://example.test/t/9",
        source_kind="search_result",
        capture_level="metadata_only",
        title="A search hit",
    )
    stored = store_item(db, hit, policy).source
    assert stored["payload_ref"] is None and stored["content_sha256"] is None
    with pytest.raises(ValueError):
        store_item(db, item(capture="metadata_only"), policy)
    with pytest.raises(ValueError):  # a search hit may not smuggle text in
        store_item(db, item(kind="search_result", capture="metadata_only"), policy)
    with pytest.raises(ValueError):  # full content needs its text
        store_item(db, item(text=None, kind="search_result"), policy)
    assert db["ai_payloads"].count_documents({}) == 0
    with pytest.raises(PermissionError):
        store_item(db, item(), current(db, "reddit"))


def test_cursor_state_advances_with_its_version(db):
    state = get_state(db, "brave_search", None, "q1")
    assert state["version"] == 0 and state["cursor"] is None
    saved = save_state(db, state, cursor="1", coverage="partial")
    saved = save_state(db, get_state(db, "brave_search", None, "q1"), cursor=None, coverage="complete_for_query")
    doc = get_state(db, "brave_search", None, "q1")
    assert doc["version"] == 2 and doc["coverage"] == "complete_for_query" and doc["last_success_at"] is not None
    assert saved["version"] == 2
