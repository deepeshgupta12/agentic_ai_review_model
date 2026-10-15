"""D71, D72 (15 Oct 2026): what the Conscient Parq run taught. A page's subject is its title and address; every web hit
read must name the project; Firecrawl search beside Brave, with the portals' project pages; single-flat listings are
not read; the run's look-back reaches the searches; a long page's evidence is where it names the project. Fictional
catalogue, hosts and texts only; the fake internet answers every provider."""

from __future__ import annotations

import json
from datetime import timedelta
from urllib.parse import parse_qs, urlsplit

import pytest
from pydantic import SecretStr

from app.connectors.base import ProviderError, QuotaExhausted
from app.connectors.firecrawl_search import FirecrawlSearch, credits_for, date_range
from app.connectors.portal_reviews import listing_page
from app.db import utcnow
from app.identity.evaluation import fictional_identities
from app.identity.evidence import densest_window
from app.identity.matching import match_text
from app.identity.queries import build_query_plan
from app.identity.rules import EVIDENCE_MAX_CHARS, QUERY_RULES_VERSION

from .conftest import FICTIONAL_CATALOGUE
from .fakenet import FakeNet, article
from .test_collection import PAGE_TEXT, coverage, run_all_jobs, start, world  # noqa: F401  (world is a fixture)

Q, T, Z = "Quillon Residences", "Tavira Vista", "Zephyrine Crest"


@pytest.fixture(scope="module")
def ids():
    return fictional_identities(json.loads(FICTIONAL_CATALOGUE.read_text(encoding="utf-8")))


def by_project(outcomes):
    return {o.project_id: o for o in outcomes}


# --- a page's subject (D71) ---------------------------------------------------------------------------------------


def test_a_portal_page_is_about_the_project_its_title_names_not_the_similar_projects_box(ids):
    text = (
        "Quillon Residences, Sector 102, Gurgaon by Brightwell Estates. 3 and 4 BHK flats.\n"
        "If you like Quillon Residences, don't miss these similar projects:\n"
        "Zephyrine Crest, Sector 65, Gurgaon. Tavira Vista, Sector 88, Gurgaon."
    )
    subject = "Quillon Residences in Sector 102, Gurgaon | Portal quillon residences sector 102 gurgaon pdpid 1"
    out = by_project(match_text(ids, text, [Q], subject=subject))
    assert out[Q].status == "auto_accepted", out[Q].rationale
    assert "multiple_projects" not in out[Q].rationale
    for other in (Z, T):
        assert (
            out[other].status == "rejected" and "in passing on a page about Quillon Residences" in out[other].rationale
        )
    # without a subject (a comment, a transcript) the old rule stands: several projects, each to review
    plain = by_project(match_text(ids, text.replace("\n", " "), [Q]))
    assert plain[Q].status == "needs_review" and "multiple_projects" in plain[Q].rationale


def test_a_page_about_another_project_never_accepts_this_one_from_its_body(ids):
    body = "Orion Heights 3.0 by Brightwell Estates. Our other projects: Quillon Residences, Sector 102, Gurgaon."
    out = by_project(match_text(ids, body, [Q], subject="Orion Heights 3.0 Sector 63A Gurgaon | Dealer"))
    assert out[Q].status == "needs_review" and "named_only_in_the_body" in out[Q].rationale
    zephyrine = "Zephyrine Crest, Sector 65 Gurgaon. Also see Quillon Residences in Sector 102."
    out = by_project(match_text(ids, zephyrine, [Q], subject="Zephyrine Crest Sector 65 Gurgaon"))
    assert out[Q].status == "rejected" and "in passing on a page about Zephyrine Crest" in out[Q].rationale


def test_a_long_pages_evidence_is_where_it_names_the_project():
    menu = "Home\nBuy\nRent\nSell\nHome Loans\n" * 300
    reviews = "Quillon Residences review: the clubhouse is open.\n" * 20
    text = menu + "About the developer\n" + reviews + "Footer\n" * 1000
    start, end = densest_window(text, "Quillon Residences")
    assert end - start == EVIDENCE_MAX_CHARS and start >= len(menu) - 300
    assert text[start:end].count("Quillon Residences") == 20
    assert densest_window(text, None) == (0, EVIDENCE_MAX_CHARS)
    assert densest_window(text, "Nowhere Towers") == (0, EVIDENCE_MAX_CHARS)


# --- Firecrawl search and the portals' project pages (D72) ----------------------------------------------------------


def test_listing_pages_are_recognised():
    assert listing_page("https://www.99acres.com/4-bhk-flat-for-sale-in-quillon-residences-sector-102-spid-P92796052")
    assert listing_page("https://www.magicbricks.com/propertyDetails/3-BHK-Flat-FOR-Sale-Sector-102&id=4d42")
    assert not listing_page("https://www.99acres.com/quillon-residences-sector-102-gurgaon-npxid-r412345")
    assert not listing_page("https://www.magicbricks.com/quillon-residences-sector-102-gurgaon-pdpid-4d42")


def test_firecrawl_takes_the_portal_project_page_queries_and_brave_does_not(db, settings, world):  # noqa: F811
    from app.sources.collection import _registry

    plan = build_query_plan(db, world["q"], _registry(settings), reviews_only=True)
    assert plan["rules_version"] == QUERY_RULES_VERSION == "query-rules.1.3"
    texts = {
        cid: [q["query_text"] for q in plan["plan"]["queries"] if q["connector_id"] == cid]
        for cid in ("brave_search", "firecrawl_search")
    }
    assert '"Quillon Residences" site:99acres.com inurl:npxid' in texts["firecrawl_search"]
    assert '"Quillon Residences" reviews site:magicbricks.com' in texts["firecrawl_search"]
    assert not any("inurl:" in t for t in texts["brave_search"])
    assert '"Quillon Residences" reviews site:magicbricks.com' in texts["brave_search"]


def firecrawl_answer(results, log):
    def answer(request):
        if request.url.path != "/v2/search":
            return 404, {"success": False, "error": "not found"}
        body = json.loads(request.content)
        log.append(body)
        return 200, {"success": True, "data": {"web": results}, "creditsUsed": credits_for(body["limit"])}

    return answer


def test_a_firecrawl_search_sends_the_window_and_country_and_reads_the_results(db, settings):
    net, log = FakeNet(), []
    net.json(
        "api.firecrawl.dev",
        firecrawl_answer(
            [
                {"url": "https://forum.example.test/t/1", "title": "Quillon Residences owners"},
                {"url": "ftp://bad.example.test/x", "title": "skipped"},
                {"url": "https://forum.example.test/t/2", "metadata": {"title": "From metadata"}},
            ],
            log,
        ),
    )
    settings.firecrawl_search_results = 20
    now = utcnow()
    search = FirecrawlSearch("test-only-firecrawl-key", net.client(), db, settings, now=lambda: now)
    page = search.discover(
        {"query_text": '"Quillon Residences" review', "window_days": 365, "exclusions": ["rent"]}, None
    )
    assert [i.canonical_url for i in page.items] == ["https://forum.example.test/t/1", "https://forum.example.test/t/2"]
    assert page.items[1].title == "From metadata" and page.next_cursor is None
    assert all(i.capture_level == "metadata_only" and i.publication_date["status"] == "unknown" for i in page.items)
    [body] = log
    assert body["country"] == "IN" and body["limit"] == 20 and body["sources"] == ["web"]
    assert body["query"] == '"Quillon Residences" review -"rent"'
    assert body["tbs"] == date_range(365, now) and f"cd_min:{now - timedelta(days=365):%m/%d/%Y}" in body["tbs"]
    assert search.health()["quota"]["used"] == 4, "2 credits per 10 results"
    assert "test-only-firecrawl-key" not in json.dumps(body)


@pytest.mark.parametrize(
    ("status", "code"), [(401, "access_refused"), (402, "quota_exhausted"), (429, "provider_busy")]
)
def test_a_refused_firecrawl_search_says_why(db, settings, status, code):
    net = FakeNet()
    net.json("api.firecrawl.dev", lambda r: (status, {"success": False, "error": "no"}))
    search = FirecrawlSearch("test-only-firecrawl-key", net.client(), db, settings)
    with pytest.raises(ProviderError) as raised:
        search.discover({"query_text": "x", "window_days": 90, "exclusions": []}, None)
    assert raised.value.code == code


def test_no_firecrawl_search_is_sent_once_the_months_credits_are_spent(db, settings):
    net = FakeNet()
    net.json("api.firecrawl.dev", lambda r: (200, {"success": True, "data": {"web": []}}))
    settings.firecrawl_monthly_credits = 3
    search = FirecrawlSearch("test-only-firecrawl-key", net.client(), db, settings)
    with pytest.raises(QuotaExhausted):
        search.discover({"query_text": "x", "window_days": 90, "exclusions": []}, None)
    assert net.requests == []


def test_a_run_searches_with_both_engines_and_reads_each_page_once(db, settings, world):  # noqa: F811
    net, log = world["net"], []
    settings.firecrawl_api_key = SecretStr("test-only-firecrawl-key")
    net.json(
        "api.firecrawl.dev",
        firecrawl_answer(
            [
                {"url": "https://forum.example.test/t/1", "title": "Quillon Residences review thread"},  # Brave's too
                {"url": "https://forum.example.test/t/2", "title": "Quillon Residences owners, Sector 102"},
                {
                    "url": "https://www.99acres.com/3-bhk-flat-for-sale-in-quillon-residences-sector-102-spid-A1",
                    "title": "3 BHK in Quillon Residences",
                },
                {"url": "https://forum.example.test/t/3", "title": "Parq Casino review"},
            ],
            log,
        ),
    )
    pages = {
        "/t/1": (200, article("Quillon Residences review", PAGE_TEXT * 4)),
        "/t/2": (200, article("Quillon Residences owners", PAGE_TEXT * 4)),
    }
    net.html("forum.example.test", pages)
    accepted = start(db, settings, world["q"], ["brave_search", "firecrawl_search", "web_fetch"])
    run_all_jobs(db)
    cov = coverage(db, accepted["run_id"])
    fc = cov["firecrawl_search"]
    assert fc["status"] == "complete_for_query" and fc["attempted_queries"] == len(log) > 0
    assert "not_read:single_listing_page" in fc["note"] and "not_read:no_project_name_in_title_or_address" in fc["note"]
    assert any("inurl:npxid" in body["query"] for body in log)
    reads = [r for r in net.requests if r.url.host == "forum.example.test" and r.url.path.startswith("/t/")]
    assert sorted(r.url.path for r in reads) == ["/t/1", "/t/2"], "each page once; the casino page is never read"
    assert cov["web_fetch"]["fetched"] == 2
    assert db["ai_run_searches"].count_documents({"_id": {"$regex": "\\|firecrawl_search\\|"}}) == len(log)


def test_a_run_with_firecrawl_alone_still_reads_pages(db, settings, world):  # noqa: F811
    settings.firecrawl_api_key = SecretStr("test-only-firecrawl-key")
    settings.brave_search_api_key = None
    world["net"].json(
        "api.firecrawl.dev",
        firecrawl_answer([{"url": "https://forum.example.test/t/1", "title": "Quillon Residences review thread"}], []),
    )
    accepted = start(db, settings, world["q"], ["firecrawl_search", "web_fetch"])
    run_all_jobs(db)
    cov = coverage(db, accepted["run_id"])
    assert cov["web_fetch"]["fetched"] == 1 and cov["firecrawl_search"]["status"] == "complete_for_query"


def test_the_runs_look_back_reaches_the_searches(db, settings, world):  # noqa: F811
    from app.sources.collection import start_run

    from .test_collection import RESEARCHER

    start_run(
        db.client,
        db,
        settings,
        world["q"],
        {"window_days": 730, "connectors": ["brave_search", "web_fetch"]},
        RESEARCHER,
    )
    run_all_jobs(db)
    brave = [r for r in world["net"].requests if r.url.host == "api.search.brave.com"]
    assert brave
    freshness = parse_qs(urlsplit(str(brave[0].url)).query)["freshness"][0]
    assert freshness.startswith((utcnow() - timedelta(days=730)).date().isoformat()), freshness


def test_an_instagram_search_that_finds_nothing_says_so(db, settings, world):  # noqa: F811
    settings.scrapfly_api_key = SecretStr("test-only-scrapfly-key")
    db["ai_project_configs"].update_one(
        {"_id": world["q"], "sources.connector_id": "instagram_public"}, {"$set": {"sources.$.enabled": True}}
    )
    world["net"].json(
        "api.search.brave.com", lambda r: (200, {"query": {"more_results_available": False}, "web": {"results": []}})
    )
    accepted = start(db, settings, world["q"], ["instagram_public"])
    run_all_jobs(db)
    note = coverage(db, accepted["run_id"])["instagram_public"]["note"]
    assert note and note.startswith("no public post or reel naming the project was found"), note
