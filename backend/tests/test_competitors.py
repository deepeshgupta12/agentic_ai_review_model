"""UC-66: refused pages of competitor portals (D60) and the open web (D61) are read through Scrapfly, and pages built
by JavaScript are rendered through Firecrawl (D62), against fakes; registry pages are never unblocked; each within a
per-job allowance and its credit ledger."""

from __future__ import annotations

import json

import httpx
from pydantic import SecretStr

from app.connectors import registry
from app.connectors.firecrawl import Firecrawl
from app.connectors.scrapfly import Scrapfly
from app.connectors.web import WebFetch
from app.sources.robots import RobotsCache

from .fakenet import FakeNet, article

REVIEW = "Quillon Residences Sector 102 owner review: possession is late but the build quality is good. " * 4


def network(scrapfly_status=200, upstream=200, firecrawl_status=200):
    net = FakeNet()
    net.html("www.99acres.com", {"/quillon-review": (403, "Access denied")})
    net.html("forum.example.test", {"/t/9": (403, "Forbidden")})
    net.html("haryanarera.gov.in", {"/view_project/9": (403, "Forbidden")})
    net.html(
        "builder.example.test",
        {"/quillon": (200, '<html><body><div id="app"></div><script>render()</script></body></html>')},
    )
    calls = []
    rendered = []

    def firecrawl(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        rendered.append((request.method, body["url"], request.headers.get("authorization", "")))
        if firecrawl_status != 200:
            return httpx.Response(firecrawl_status, headers={"content-type": "application/json"}, content=b"{}")
        page = article("Quillon Residences builder page", REVIEW)
        out = {"success": True, "data": {"rawHtml": page, "metadata": {"statusCode": 200}}, "creditsUsed": 1}
        return httpx.Response(200, headers={"content-type": "application/json"}, content=json.dumps(out).encode())

    net.route("api.firecrawl.dev", firecrawl)
    net.rendered = rendered

    def scrapfly(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.params["url"])
        headers = {"content-type": "application/json", "x-scrapfly-api-cost": "25"}
        if scrapfly_status != 200:
            return httpx.Response(scrapfly_status, headers=headers)
        body = {"result": {"status_code": upstream, "content": article("Quillon Residences review", REVIEW)}}
        return httpx.Response(200, headers=headers, content=json.dumps(body).encode())

    net.route("api.scrapfly.io", scrapfly)
    return net, calls


def reader(db, settings, net, limit=5, with_scrapfly=True, with_firecrawl=True, render_limit=5):
    client = net.client()
    scrapfly = Scrapfly("test-only-scrapfly-key-0000", client, db, settings) if with_scrapfly else None
    firecrawl = Firecrawl("test-only-firecrawl-key-0000", client, db, settings) if with_firecrawl else None
    return WebFetch(client, RobotsCache(client, "ProjectIntelligenceBot"), db, scrapfly, limit, firecrawl, render_limit)


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


def test_the_open_web_and_registries_are_unblocked_but_blocked_families_are_never_fetched(db, settings, contracts):
    net, calls = network()
    outcome = reader(db, settings, net).fetch("https://forum.example.test/t/9")
    assert outcome.status == "fetched" and outcome.reason == "fetched_unblocked", (
        "any public host, refusal retried (D61)"
    )
    registry = reader(db, settings, net).fetch("https://haryanarera.gov.in/view_project/9")
    assert registry.reason == "fetched_unblocked", "official records too: every data (D61)"
    platform = reader(db, settings, net).fetch("https://www.reddit.com/r/gurgaon/1")
    assert platform.status == "not_allowed" and len(calls) == 2, "a family that blocks collection is never fetched"


def test_a_page_built_by_javascript_is_rendered_through_firecrawl_once(db, settings, contracts):
    net, _ = network()
    web = reader(db, settings, net, render_limit=1)
    outcome = web.fetch("https://builder.example.test/quillon")
    assert outcome.status == "fetched" and outcome.reason == "fetched_rendered" and "build quality" in outcome.item.text
    [(method, url, auth)] = net.rendered
    assert method == "POST" and url == "https://builder.example.test/quillon" and auth.startswith("Bearer ")
    entry = db["ai_fetch_log"].find_one({"outcome": "fetched_rendered"})
    assert entry["provider_credits"] == 1 and "test-only-firecrawl-key" not in json.dumps(entry, default=str)
    second = web.fetch("https://builder.example.test/quillon")
    assert second.status == "thin" and "allowance" in second.reason and len(net.rendered) == 1


def test_firecrawl_refusals_and_missing_keys_leave_the_page_thin(db, settings, contracts):
    net, _ = network(firecrawl_status=402)
    outcome = reader(db, settings, net).fetch("https://builder.example.test/quillon")
    assert outcome.status == "thin" and "quota_exhausted" in outcome.reason
    net, _ = network()
    assert (
        reader(db, settings, net, with_firecrawl=False).fetch("https://builder.example.test/quillon").status == "thin"
    )
    assert net.rendered == []


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
