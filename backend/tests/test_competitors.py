"""UC-66: competitor portals that refuse the web reader are read through Scrapfly (D60), against fakes. Only the
competitor_portals family is unblocked, within a per-job allowance and the shared credit ledger."""

from __future__ import annotations

import json

import httpx
from pydantic import SecretStr

from app.connectors import registry
from app.connectors.scrapfly import Scrapfly
from app.connectors.web import WebFetch
from app.sources.robots import RobotsCache

from .fakenet import FakeNet, article
from .test_collection import allow_forum

REVIEW = "Quillon Residences Sector 102 owner review: possession is late but the build quality is good. " * 4


def network(scrapfly_status=200, upstream=200):
    net = FakeNet()
    net.html("www.99acres.com", {"/quillon-review": (403, "Access denied")})
    net.html("forum.example.test", {"/t/9": (403, "Forbidden")})
    calls = []

    def scrapfly(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.params["url"])
        headers = {"content-type": "application/json", "x-scrapfly-api-cost": "25"}
        if scrapfly_status != 200:
            return httpx.Response(scrapfly_status, headers=headers)
        body = {"result": {"status_code": upstream, "content": article("Quillon Residences review", REVIEW)}}
        return httpx.Response(200, headers=headers, content=json.dumps(body).encode())

    net.route("api.scrapfly.io", scrapfly)
    return net, calls


def reader(db, settings, net, limit=5, with_scrapfly=True):
    client = net.client()
    scrapfly = Scrapfly("test-only-scrapfly-key-0000", client, db, settings) if with_scrapfly else None
    return WebFetch(client, RobotsCache(client, "ProjectIntelligenceBot"), db, scrapfly, limit)


def test_a_refused_competitor_page_is_read_through_scrapfly_and_logged(db, settings, contracts):
    net, calls = network()
    outcome = reader(db, settings, net).fetch("https://www.99acres.com/quillon-review")
    assert (
        outcome.status == "fetched" and outcome.reason == "fetched_unblocked" and "build quality" in outcome.item.text
    )
    assert calls == ["https://www.99acres.com/quillon-review"]
    logs = [
        log["outcome"]
        for log in db["ai_fetch_log"].find({"url": "https://www.99acres.com/quillon-review"}).sort("at", 1)
    ]
    assert logs == ["refused", "fetched_unblocked"], "the refusal and the Scrapfly read are both recorded"
    entry = db["ai_fetch_log"].find_one({"outcome": "fetched_unblocked"})
    assert entry["provider_credits"] == 25 and entry["family"] == "competitor_portals"
    assert "test-only-scrapfly-key" not in json.dumps(entry, default=str)


def test_only_competitor_portals_are_unblocked(db, settings, contracts):
    allow_forum(db, contracts)
    net, calls = network()
    outcome = reader(db, settings, net).fetch("https://forum.example.test/t/9")
    assert outcome.status == "refused" and calls == [], "a refused page of any other family is not worked around"


def test_the_per_job_allowance_bounds_the_unblocking(db, settings, contracts):
    net, calls = network()
    web = reader(db, settings, net, limit=1)
    assert web.fetch("https://www.99acres.com/quillon-review").status == "fetched"
    second = web.fetch("https://www.99acres.com/quillon-review")
    assert second.status == "refused" and "allowance" in second.reason and len(calls) == 1


def test_the_months_credits_bound_the_unblocking(db, settings, contracts):
    settings.scrapfly_monthly_credits = settings.scrapfly_credits_per_post  # one page's worth this month
    net, calls = network()
    assert reader(db, settings, net).fetch("https://www.99acres.com/quillon-review").status == "fetched"
    second = reader(db, settings, net).fetch("https://www.99acres.com/quillon-review")
    assert second.status == "refused" and "credits" in second.reason and len(calls) == 1, "no request without credits"


def test_a_page_refused_even_through_scrapfly_stays_refused(db, settings, contracts):
    net, _ = network(upstream=403)
    outcome = reader(db, settings, net).fetch("https://www.99acres.com/quillon-review")
    assert outcome.status == "refused" and "even through Scrapfly" in outcome.reason
    net, _ = network(scrapfly_status=401)
    outcome = reader(db, settings, net).fetch("https://www.99acres.com/quillon-review")
    assert outcome.status == "refused" and "access_refused" in outcome.reason


def test_without_a_scrapfly_key_refusals_stay_refused(db, settings, contracts):
    net, calls = network()
    assert (
        reader(db, settings, net, with_scrapfly=False).fetch("https://www.99acres.com/quillon-review").status
        == "refused"
    )
    settings.scrapfly_api_key = None
    web = registry.build("web_fetch", db, settings)
    assert web.unblocker is None and calls == []
    settings.scrapfly_api_key = SecretStr("test-only-scrapfly-key-0000")
    assert registry.build("web_fetch", db, settings).unblock_left == settings.unblocked_pages_per_run
