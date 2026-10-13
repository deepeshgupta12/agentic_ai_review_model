"""UC-66: Google Alerts by RSS as the free listening source (D56), against a fake feed. No real feed is read; the
connector stays access_pending until the product owner's feed addresses are configured and one is read."""

from __future__ import annotations

import httpx
from pydantic import SecretStr

from app.connectors import registry
from app.connectors.alerts import feed_list, names_project, parse_feed, redacted, target_of
from app.sources import collection

from .fakenet import FakeNet, article
from .test_collection import PAGE_TEXT, allow_forum, run_all_jobs, start

FEED = "https://www.google.com/alerts/feeds/01234567890123456789/9876543210987654321"
OTHER_FEED = "https://www.google.com/alerts/feeds/01234567890123456789/1111111111111111111"


def entry(url: str, title: str, when: str = "2026-10-12T09:30:00Z") -> str:
    link = f"https://www.google.com/url?rct=j&amp;sa=t&amp;url={url}&amp;ct=ga&amp;cd=CAEY&amp;usg=AOvVaw"
    return (
        f'<entry><id>tag:google.com,2013:googlealerts/feed:1</id><title type="html">{title}</title>'
        f'<link href="{link}"/><published>{when}</published><updated>{when}</updated>'
        '<content type="html">a snippet that is never stored</content></entry>'
    )


def feed(query: str, entries: list[str]) -> str:
    return (
        '<?xml version="1.0" encoding="utf-8"?><feed xmlns="http://www.w3.org/2005/Atom">'
        f"<id>tag:google.com,2005:reader/user/1/state/com.google/alerts/2</id><title>Google Alert - {query}</title>"
        f"<updated>2026-10-12T10:00:00Z</updated>{''.join(entries)}</feed>"
    )


QUILLON = feed(
    '"Quillon Residences"',
    [
        entry("https://forum.example.test/t/9", "&lt;b&gt;Quillon Residences&lt;/b&gt; owners meet the builder"),
        entry("https://www.youtube.com/watch?v=vid9", "A video about &lt;b&gt;Quillon&lt;/b&gt;"),
        entry("https://www.reddit.com/r/gurgaon/comments/9", "Reddit thread"),
    ],
)
TAVIRA = feed('"Tavira Vista"', [entry("https://forum.example.test/t/77", "Tavira Vista news")])


def network():
    net = FakeNet()

    def google(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return httpx.Response(
                200, headers={"content-type": "text/plain"}, text="User-agent: *\nDisallow: /alerts/\n"
            )
        body = {FEED: QUILLON, OTHER_FEED: TAVIRA}.get(str(request.url).split("?")[0])
        if body is None:
            return httpx.Response(404, headers={"content-type": "text/html"}, text="no such feed")
        return httpx.Response(200, headers={"content-type": "application/atom+xml; charset=utf-8"}, text=body)

    net.route("www.google.com", google)
    net.html(
        "forum.example.test", {"/t/9": (200, article("Quillon Residences owners meet the builder", PAGE_TEXT * 4))}
    )
    return net


def test_feed_addresses_entries_and_targets_are_read_strictly():
    assert feed_list(f"{FEED} junk, {OTHER_FEED}\n{FEED} https://example.com/x") == [FEED, OTHER_FEED]
    assert target_of("https://www.google.com/url?rct=j&sa=t&url=https://forum.example.test/t/9&ct=ga") == (
        "https://forum.example.test/t/9"
    )
    title, entries = parse_feed(QUILLON.encode())
    assert title == 'Google Alert - "Quillon Residences"' and len(entries) == 3
    assert entries[0]["title"] == "Quillon Residences owners meet the builder", "Google's bold tags are removed"
    assert entries[0]["found_at"].isoformat() == "2026-10-12T09:30:00+00:00"
    assert names_project(title, ["quillon residences"]) and not names_project(title, ["tavira vista"])
    assert redacted(FEED) == "https://www.google.com/alerts/feeds/<private>"


def test_without_feed_addresses_the_connector_is_not_built(db, settings):
    assert registry.build("google_alerts", db, settings) is None
    settings.google_alerts_feeds = SecretStr("not a feed")
    assert registry.build("google_alerts", db, settings) is None


def test_a_run_reads_the_projects_alert_and_the_allow_listed_pages_it_names(
    db, settings, contracts, fictional, monkeypatch
):
    allow_forum(db, contracts)
    net = network()
    settings.google_alerts_feeds = SecretStr(f"{FEED} {OTHER_FEED}")
    settings.brave_search_api_key = SecretStr("test-only-brave-key-0000")  # the web reader runs with discovery
    settings.crawler_min_seconds_per_host = 0
    net.json(
        "api.search.brave.com", lambda r: (200, {"query": {"more_results_available": False}, "web": {"results": []}})
    )
    monkeypatch.setattr(registry, "safe_client", lambda _s: net.client())
    monkeypatch.setattr(collection, "get_settings", lambda: settings)
    q = fictional["Quillon Residences"]
    db["ai_project_configs"].update_one(
        {"_id": q, "sources.connector_id": "google_alerts"}, {"$set": {"sources.$.enabled": True}}
    )
    accepted = start(db, settings, q, connectors=["brave_search", "google_alerts"])
    run_all_jobs(db)
    cov = {c["connector_id"]: c for c in db["ai_runs"].find_one({"_id": accepted["run_id"]})["coverage"]}
    alerts = cov["google_alerts"]
    assert alerts["attempted_queries"] == 2, "one feed read and one page requested"
    assert alerts["fetched"] == 1 and alerts["matched"] == 1
    note = alerts["note"]
    assert "feeds_for_other_projects: 1" in note, "the Tavira Vista alert is not this project's"
    assert "youtube_left_to_its_connector: 1" in note and "not_collected:reddit: 1" in note
    mention = db["ai_sources"].find_one({"connector_id": "google_alerts"})
    assert mention["source_kind"] == "search_result" and mention["capture_level"] == "metadata_only"
    assert mention["publication_date"]["status"] == "approximate", "when Google found it, never the page's date"
    page = db["ai_sources"].find_one({"connector_id": "web_fetch", "native_id": "https://forum.example.test/t/9"})
    assert page is not None and page["capture_level"] == "full_content"
    logs = list(db["ai_fetch_log"].find({"connector_id": "google_alerts"}))
    assert {log["url"] for log in logs} == {"https://www.google.com/alerts/feeds/<private>"}, "feed ids never logged"
    assert all(log["robots"].startswith("disallowed") and log["outcome"] == "fetched" for log in logs)
    assert "a snippet that is never stored" not in str(list(db["ai_sources"].find()))
