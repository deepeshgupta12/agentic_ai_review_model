"""UC-64: Instagram public posts through Scrapfly (D54), against a fake Scrapfly and Brave. No real request is made;
the connector stays access_pending until a real key reads a real post."""

from __future__ import annotations

import json

import httpx
import pytest
from pydantic import SecretStr

from app.connectors import registry
from app.connectors.base import ProviderError, QuotaExhausted
from app.connectors.instagram import InstagramPublic, parse_post, post_url
from app.connectors.scrapfly import Scrapfly
from app.sources import collection
from app.sources.http import FetchError
from app.sources.robots import RobotsCache

from .fakenet import FakeNet
from .test_collection import run_all_jobs, start

CAPTION = "Site visit at Quillon Residences, Sector 102 Gurugram: tower 3 slab work done, lifts not yet installed."


def post_page(code="Cq1AbCdEfGh", caption=CAPTION, gated=False):
    media = {
        "pk": "311",
        "code": code,
        "taken_at": 1757500000,
        "caption": {"text": caption},
        "user": {"username": "gurgaon_homes"},
    }
    payload = {
        "require": [["ScheduledServerJS", {"xig_polaris_media": {"if_not_gated_logged_out": {"items": [media]}}}]]
    }
    script = (
        "" if gated else f'<script type="application/json" data-content-len="9" data-sjs>{json.dumps(payload)}</script>'
    )
    return f"<html><head><title>Instagram</title></head><body>{script}</body></html>"


class FakeScrapfly:
    def __init__(self, status=200, upstream=200, page=None, cost="30"):
        self.status, self.upstream, self.page, self.cost = status, upstream, page, cost
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        headers = {"content-type": "application/json", "x-scrapfly-api-cost": self.cost}
        if self.status != 200:
            return httpx.Response(self.status, headers={**headers, "x-scrapfly-reject-code": "ERR::ASP::SHIELD"})
        target = request.url.params["url"]
        code = target.rstrip("/").rsplit("/", 1)[-1]
        body = {
            "result": {"status_code": self.upstream, "content": self.page if self.page is not None else post_page(code)}
        }
        return httpx.Response(200, headers=headers, content=json.dumps(body).encode())


def network(scrapfly):
    net = FakeNet()
    net.route("api.scrapfly.io", scrapfly)
    net.html("www.instagram.com", {}, robots="User-agent: *\nDisallow: /\n")  # Instagram disallows unlisted crawlers

    def brave(request):
        q = request.url.params["q"]
        results = (
            [
                {"url": "https://www.instagram.com/p/Cq1AbCdEfGh/?igsh=abc", "title": "Quillon Residences update"},
                {"url": "https://www.instagram.com/reel/Dz9XyZ12345/", "title": "Quillon Residences reel"},
                {"url": "https://www.instagram.com/gurgaon_homes/", "title": "A profile"},
            ]
            if q.startswith("site:instagram.com")
            else [{"url": "https://www.instagram.com/p/Cq1AbCdEfGh/", "title": "seen by the web group too"}]
        )
        return 200, {"query": {"more_results_available": False}, "web": {"results": results}}

    net.json("api.search.brave.com", brave)
    return net


def connector(db, settings, net):
    settings.scrapfly_api_key = SecretStr("test-only-scrapfly-key-0000")
    settings.brave_search_api_key = SecretStr("test-only-brave-key-0000")
    client = net.client()
    brave = registry.build("brave_search", db, settings)
    brave.client = client
    scrapfly = Scrapfly("test-only-scrapfly-key-0000", client, db, settings)
    return InstagramPublic(scrapfly, RobotsCache(client, "ProjectIntelligenceBot"), db, settings, brave)


def test_only_post_and_reel_addresses_are_read():
    assert post_url("https://instagram.com/p/Cq1AbCdEfGh/?igsh=x") == (
        "https://www.instagram.com/p/Cq1AbCdEfGh/",
        "Cq1AbCdEfGh",
    )
    assert post_url("https://www.instagram.com/reels/Dz9XyZ12345") == (
        "https://www.instagram.com/reel/Dz9XyZ12345/",
        "Dz9XyZ12345",
    )
    assert post_url("https://www.instagram.com/gurgaon_homes/") is None
    assert post_url("https://www.instagram.com/accounts/login/") is None


def test_the_post_comes_from_the_logged_out_page_and_a_gated_page_gives_nothing():
    post = parse_post(post_page(), "Cq1AbCdEfGh")
    assert post["caption"]["text"] == CAPTION and post["user"]["username"] == "gurgaon_homes"
    assert parse_post(post_page(), "OtherCode123") is None, "only the post asked for"
    assert parse_post(post_page(gated=True), "Cq1AbCdEfGh") is None


def test_a_post_is_read_through_scrapfly_with_policy_robots_and_credits_recorded(db, settings):
    scrapfly = FakeScrapfly()
    ig = connector(db, settings, network(scrapfly))
    item = ig.fetch_item("https://www.instagram.com/p/Cq1AbCdEfGh/", run_id="run_01K00000000000000000000001")
    assert item.text == CAPTION and item.source_kind == "forum_post" and item.author["display_name"] == "gurgaon_homes"
    assert item.publication_date["basis"] == "platform_metadata" and item.publication_date["precision"] == "instant"
    [request] = scrapfly.requests
    params = request.url.params
    assert params["unblocker"] == "true" and params["proxy_pool"] == "public_residential_pool"
    assert params["url"] == "https://www.instagram.com/p/Cq1AbCdEfGh/" and params["render_js"] == "false"
    log = db["ai_fetch_log"].find_one({"connector_id": "instagram_public"})
    assert log["outcome"] == "fetched" and log["family"] == "instagram_public" and log["provider_credits"] == 30
    assert log["robots"].startswith("disallowed"), "robots.txt is asked and recorded; the policy does not enforce it"
    assert "test-only-scrapfly-key" not in json.dumps(log, default=str), "the key is never logged"
    assert ig.scrapfly.credits()["used"] == settings.scrapfly_credits_per_post, "one ledger, shared with D60"


@pytest.mark.parametrize(
    ("scrapfly", "expected"),
    [
        (FakeScrapfly(upstream=404), "gone"),
        (FakeScrapfly(page=post_page(gated=True)), "no_public_post"),
        (FakeScrapfly(upstream=403), "refused"),
        (FakeScrapfly(status=422), "scrape_failed"),
    ],
)
def test_removed_gated_or_refused_posts_are_recorded_and_not_worked_around(db, settings, scrapfly, expected):
    ig = connector(db, settings, network(scrapfly))
    with pytest.raises(FetchError) as caught:
        ig.fetch_item("Cq1AbCdEfGh")
    assert caught.value.code == expected and len(scrapfly.requests) == 1, "one request, no second attempt"


def test_a_refused_key_and_spent_credits_stop_the_connector(db, settings):
    ig = connector(db, settings, network(FakeScrapfly(status=401)))
    with pytest.raises(ProviderError, match="refused"):
        ig.fetch_item("Cq1AbCdEfGh")
    scrapfly = FakeScrapfly()
    ig = connector(db, settings, network(scrapfly))
    settings.scrapfly_monthly_credits = settings.scrapfly_credits_per_post - 1
    with pytest.raises(QuotaExhausted):
        ig.fetch_item("Cq1AbCdEfGh")
    assert scrapfly.requests == [], "credits are reserved before the request, so none is made"


def test_without_a_scrapfly_key_instagram_stays_access_pending(db, settings):
    settings.brave_search_api_key = SecretStr("test-only-brave-key-0000")
    assert registry.build("instagram_public", db, settings) is None


def test_a_run_reads_the_projects_public_posts(db, settings, contracts, fictional, monkeypatch):
    scrapfly = FakeScrapfly()
    net = network(scrapfly)
    settings.scrapfly_api_key = SecretStr("test-only-scrapfly-key-0000")
    settings.brave_search_api_key = SecretStr("test-only-brave-key-0000")
    settings.crawler_min_seconds_per_host = 0
    monkeypatch.setattr(registry, "safe_client", lambda _s: net.client())
    monkeypatch.setattr(collection, "get_settings", lambda: settings)
    q = fictional["Quillon Residences"]
    db["ai_project_configs"].update_one(
        {"_id": q, "sources.connector_id": "instagram_public"}, {"$set": {"sources.$.enabled": True}}
    )
    accepted = start(db, settings, q, connectors=["brave_search", "instagram_public"])
    run_all_jobs(db)
    run = db["ai_runs"].find_one({"_id": accepted["run_id"]})
    cov = {c["connector_id"]: c for c in run["coverage"]}
    assert cov["instagram_public"]["fetched"] == 2 and cov["instagram_public"]["matched"] == 2
    assert "not_a_post: 2" in cov["instagram_public"]["note"], "a profile page is not a post"
    asked = [r.url.params["q"] for r in net.requests if r.url.host == "api.search.brave.com"]
    assert 'site:instagram.com "Quillon Residences"' in [q.split(" -")[0] for q in asked], "the name is searched quoted"
    assert "instagram_left_to_instagram_connector" in cov["brave_search"]["note"]
    posts = list(db["ai_sources"].find({"connector_id": "instagram_public"}))
    assert {p["source_kind"] for p in posts} == {"forum_post"} and {p["policy"]["family"] for p in posts} == {
        "instagram_public"
    }
    assert db["ai_evidence"].count_documents({"source.id": {"$in": [p["id"] for p in posts]}}) == 2
    again = start(db, settings, q, connectors=["brave_search", "instagram_public"])
    run_all_jobs(db)
    cov = {c["connector_id"]: c for c in db["ai_runs"].find_one({"_id": again["run_id"]})["coverage"]}
    assert "already_read: 2" in cov["instagram_public"]["note"] and len(scrapfly.requests) == 2, "each post read once"
