# ruff: noqa: F811  (fixtures are imported from the collection, workflow and review-first tests)
"""The audit of 14 Oct 2026, after the first live run: each test is one failure the audit found, checked against its
fix. Fictional projects, pages and texts only; no network and no model call."""

from __future__ import annotations

import base64
import json
import threading
import time
from datetime import timedelta

import anthropic
import httpx
import pytest

from app.agents.common import record_run
from app.agents.gateway import GatewayResult, ModelGateway
from app.agents.spend import BUDGETS, HOLDS, SpendLedger, release_stale_holds
from app.connectors import portal_reviews as pr
from app.connectors.reddit import _skip, _skip_post
from app.db import utcnow
from app.errors import ApiError
from app.jobs import queue
from app.sources import collection
from app.sources.collection import NameKeys, cancel_run, names_the_project
from app.sources.http import FetchError, Response
from app.sources.store import Item

from .conftest import sign_in
from .fakenet import FakeNet
from .test_collection import RESEARCHER, coverage, run_all_jobs, start, world  # noqa: F401
from .test_gateway import api_error
from .test_recheck import recheck
from .test_review_first import MORE, OWNER, PROJECT_PAGE, RESIDENT, ld, magicbricks_page, mb, portal, serve
from .test_workflow import analysing_run, model, work  # noqa: F401

# --- pages that would have crashed a whole collect job -------------------------------------------------------------


def test_an_unknown_charset_is_read_as_utf8():
    page = Response("https://x.test/", 200, {"content-type": "text/html; charset=utf8mb4"}, "Quillon héllo".encode())
    assert page.text() == "Quillon héllo"


def test_a_corrupt_body_fails_that_page_only():
    net = FakeNet()
    net.route(
        "bad.example.test",
        lambda r: httpx.Response(
            200, headers={"content-type": "text/html", "content-encoding": "gzip"}, content=b"not gzip at all"
        ),
    )
    with pytest.raises(FetchError) as info:
        net.client().get("https://bad.example.test/page")
    assert info.value.code == "bad_response"


def test_a_paid_post_is_never_sent_again_after_a_timeout():
    sent = []

    def slow(request):
        sent.append(request)
        raise httpx.ReadTimeout("slow", request=request)

    net = FakeNet()
    net.route("api.firecrawl.dev", slow)
    with pytest.raises(FetchError) as info:
        net.client().post_json("https://api.firecrawl.dev/v1/scrape", {"url": "https://x.test/"})
    assert info.value.code == "timeout" and len(sent) == 1, "a resend could be billed again"


@pytest.mark.parametrize(
    "state",
    [
        {"projectPageSeoStaticData": "unexpected"},
        {"projectPageSeoStaticData": {"projectReviews": ["a list"]}},
        {"projectPageSeoStaticData": {"projectReviews": {"resultList": [None, 3, "x"], "count": "x"}}},
    ],
)
def test_an_unexpected_magicbricks_state_never_crashes(state):
    page = f"<script>window.SERVER_PRELOADED_STATE_ = {json.dumps(state)};</script>"
    assert pr.magicbricks(page, PROJECT_PAGE).reviews == []


def test_99acres_without_its_page_state_keeps_no_review():
    found = pr.ninety_nine_acres(ld({"@type": "Review", "reviewBody": OWNER}))
    assert found.reviews == [] and found.dropped == {"locality_guard_unavailable": 1}


def test_the_full_review_list_followed_is_the_projects_own():
    other = "https://www.magicbricks.com/brightwell-towers-reviews-pdpid-9999"
    page = magicbricks_page([mb("r1", OWNER)], count=5, link=False) + f'<a href="{other}">x</a><a href="{MORE}">y</a>'
    assert pr.magicbricks(page, PROJECT_PAGE).more_url == MORE


def test_a_deleted_authors_post_keeps_its_thread_and_an_empty_comment_is_skipped():
    assert not _skip_post({"id": "p", "author": "[deleted]", "title": "Quillon Residences?", "selftext": "[removed]"})
    assert _skip_post({"id": "p", "author": "AutoModerator", "title": "Rules"})
    assert _skip({"id": "c", "author": "someone", "body": None}), "None is not the word None"


# --- the project's name in a search hit ----------------------------------------------------------------------------


def hit(url, title):
    return Item(
        connector_id="brave_search",
        native_id=url,
        canonical_url=url,
        source_kind="search_result",
        capture_level="metadata_only",
        title=title,
    )


def test_the_project_name_is_recognised_in_its_usual_forms():
    keys = NameKeys(names=[["dlf", "privana"]], own=[["privana"]], places=["sector 77", "gurgaon", "gurugram"])
    for url, title in [
        ("https://www.quora.com/Is-Privana-by-DLF-a-good-investment", "Is Privana by DLF a good investment?"),
        ("https://www.magicbricks.com/dlfprivana-sector-76-gurgaon-pdpid-1", ""),
        ("https://housing.com/in/buy/projects/page/315591-privana-south-by-dlf-in-sector-77", ""),
        ("https://x.test/a", "डीएलएफ प्राइवाना"),
        ("https://x.test/b", "Privana South, Sector 77 Gurgaon: a resident's view"),
    ]:
        assert names_the_project(hit(url, title), keys), url
    assert not names_the_project(
        hit("https://www.magicbricks.com/dlf-the-magnolias-pdpid-2", "DLF The Magnolias"), keys
    )


def test_a_short_name_without_its_place_or_developer_is_not_the_project():
    """15 Oct 2026: "parq" alone read Parq Casino, Parqet, parking apps and French pages on "conscience"."""
    keys = NameKeys(names=[["conscient", "parq"]], own=[["parq"]], places=["sector 80", "gurgaon", "gurugram"])
    for url, title in [
        ("https://en.wikipedia.org/wiki/Parq_Casino", "Parq Casino - Wikipedia"),
        ("https://www.finanzlennard.de/en/blog/parqet-review", "Parqet Review 2026"),
        ("https://www.apartments.com/parq-on-5th-apartments-tempe-az/wevrjgh", "Parq on 5th Apartments"),
        ("https://fr.wikipedia.org/wiki/Conscience", "Conscience — Wikipédia"),
        ("https://conscient.in/elevate", "Luxury Apartments in Sector 59, Gurgaon - Elevate"),
    ]:
        assert not names_the_project(hit(url, title), keys), url
    for url, title in [
        ("https://www.magicbricks.com/conscient-parq-sector-80-gurgaon-pdpid-4d42", "Conscient PARQ in Sector 80"),
        ("https://x.test/c", "Parq, Sector 80 Gurugram: possession update"),
    ]:
        assert names_the_project(hit(url, title), keys), url


# --- a collect job retried after a crash ---------------------------------------------------------------------------


def test_a_web_job_retried_after_a_crash_reads_its_pages_without_searching_again(db, settings, world, monkeypatch):
    real = collection.Collector._known
    calls = {"n": 0}

    def hiccup(self, url, outcomes):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("database hiccup")
        return real(self, url, outcomes)

    monkeypatch.setattr(collection.Collector, "_known", hiccup)
    run_id = start(db, settings, world["q"], connectors=["brave_search"])["run_id"]
    run_all_jobs(db)
    first = coverage(db, run_id)
    assert first["web_fetch"]["status"] == "partial" and first["web_fetch"]["note"].startswith("stopped: error")
    searches = world["net"].hosts_requested().count("api.search.brave.com")
    db["ai_jobs"].update_many({"status": "retry_wait"}, {"$set": {"next_attempt_at": utcnow()}})
    run_all_jobs(db)
    final = coverage(db, run_id)
    assert world["net"].hosts_requested().count("api.search.brave.com") == searches, "finished searches are reused"
    assert final["web_fetch"]["fetched"] == 1 and final["web_fetch"]["status"] == "complete_for_query"
    assert final["brave_search"]["status"] == "complete_for_query"


def test_a_cancelled_run_says_its_sources_did_not_finish(db, settings, contracts, world):
    run_id = start(db, settings, world["q"])["run_id"]
    cancel_run(db.client, db, contracts, run_id, "Wrong window", RESEARCHER)
    cov = coverage(db, run_id)
    assert not any((c["note"] or "").startswith(("queued", "in progress")) for c in cov.values())
    assert cov["web_fetch"]["status"] == "unavailable" and cov["web_fetch"]["note"] == "stopped: the run was cancelled"


def test_a_second_run_waits_for_the_first(db, settings, world):
    start(db, settings, world["q"])
    with pytest.raises(ApiError) as info:
        start(db, settings, world["q"])
    assert info.value.status == 409 and "still working" in str(info.value)


def test_reviews_of_one_page_are_rechecked_with_one_fetch_of_it(db, settings, world, monkeypatch):
    two = magicbricks_page([mb("r1", OWNER), mb("r2", RESIDENT, relation="Lives in Project")], link=False)
    net, _ = portal(db, settings, world, monkeypatch)
    serve(net, two, two)
    page_path = PROJECT_PAGE.removeprefix("https://www.magicbricks.com")
    before = [r.url.path for r in net.requests].count(page_path)
    recheck(db)
    fetched = [r.url.path for r in net.requests].count(page_path) - before
    assert fetched == 2, "the page source itself once, and once shared by its reviews"


# --- analysis and page building that stop must say so, and continue ------------------------------------------------


def a11_fails_with(model, error):
    """The scripted model answers A11 with a provider error (a bad request is not retried and cannot be split)."""
    answer = model.create

    def create(**kwargs):
        system = kwargs["system"] if isinstance(kwargs["system"], str) else kwargs["system"][0]["text"]
        if system.startswith("You are A11") and model.failing:
            model.calls.append("A11")
            raise error
        return answer(**kwargs)

    model.failing = True
    model.create = create


def test_a_task_failing_the_same_way_twice_is_skipped_and_reported(db, settings, contracts, fictional, model):
    settings.analysis_mode = "reviews"
    a11_fails_with(model, api_error(anthropic.BadRequestError, 400))
    _, run = analysing_run(db, settings, contracts, fictional)
    work(db)
    stopped = db["ai_runs"].find_one({"_id": run["_id"]})
    assert stopped["stage"] == "analysing" and stopped["outcome_note"].startswith(
        "Analysis stopped: reviews_unfinished"
    )
    from app.workflows.analysis import analyse_again

    analyse_again(db, run["_id"])
    work(db)
    ended = db["ai_runs"].find_one({"_id": run["_id"]})
    assert ended["stage"] == "insufficient_evidence", "the same failure twice does not block every Continue"
    assert "could not read some passages and skipped them" in ended["outcome_note"]


def test_the_scheduler_queues_a_missing_analysis_and_explains_a_dead_one(db, settings, contracts, fictional, model):
    from app.scheduler.main import sweep_analyses

    _, run = analysing_run(db, settings, contracts, fictional)
    db["ai_jobs"].delete_many({"run_id": run["_id"], "kind": "analyse"})
    assert sweep_analyses(db) == 1 and db["ai_jobs"].count_documents({"run_id": run["_id"], "kind": "analyse"}) == 1
    db["ai_jobs"].update_many(
        {"run_id": run["_id"], "kind": "analyse"},
        {"$set": {"status": "failed", "error": {"code": "ValueError", "message": "boom", "retryable": False}}},
    )
    assert sweep_analyses(db) == 1
    assert db["ai_runs"].find_one({"_id": run["_id"]})["outcome_note"].startswith("Analysis stopped: ValueError")
    assert sweep_analyses(db) == 0, "said once"


def test_a_resume_job_that_failed_can_be_asked_for_again(db, settings, contracts, fictional, model):
    from app.workflows import analysis

    settings.analysis_mode = "reviews"
    settings.review_words_min = 1
    q, _ = analysing_run(db, settings, contracts, fictional)
    work(db)
    db["ai_review_excerpts"].update_many({"project_id": q}, {"$set": {"review_status": "approved"}})
    refs = [{"id": r["id"], "revision": r["revision"]} for r in db["ai_review_excerpts"].find({"project_id": q})]
    body = {"mode": "generate", "locale": "en-IN", "findings": [], "reviews": refs + refs}  # a duplicate as well
    moderator = {"kind": "user", "user_id": "usr_01K00000000000000000000002", "role": "moderator"}
    first = analysis.request_resume(db, q, body, moderator)
    job = db["ai_jobs"].find_one({"_id": first["job_id"]})
    assert len(job["resume_event"]["reviews"]) == len(refs), "each review once"
    db["ai_jobs"].update_one({"_id": job["_id"]}, {"$set": {"status": "failed"}})
    again = analysis.request_resume(db, q, body, moderator)
    assert again["job_id"] != first["job_id"], "a new job, not the failed one returned again"


# --- the model budget ----------------------------------------------------------------------------------------------


class Raising:
    def __init__(self, error):
        self.error = error
        self.messages = self

    def create(self, **kwargs):
        raise self.error


def test_a_call_that_raises_gives_its_budget_hold_back(db, settings, contracts):
    ledger = SpendLedger(db, settings)
    gateway = ModelGateway(settings, contracts, client=Raising(ValueError("streaming required")), ledger=ledger)
    with pytest.raises(ValueError):
        gateway.run("light", "agents.schema.json#/$defs/ReviewCandidates", "You are A11", "x", max_tokens=1000)
    assert ledger.state()["reserved_usd"] == 0 and db[HOLDS].count_documents({}) == 0


def test_a_hold_left_by_a_stopped_worker_is_given_back_once(db, settings):
    ledger = SpendLedger(db, settings)
    held = ledger.reserve(settings.model_for_role("light"), 0.5, batch=False)
    assert held is not None and ledger.state()["reserved_usd"] == 0.5
    db[HOLDS].update_many({}, {"$set": {"at": utcnow() - timedelta(hours=2)}})
    assert release_stale_holds(db) == 1 and ledger.state()["reserved_usd"] == 0
    ledger.settle(held, None, purpose="late", outcome="not_billed")  # the call finished after all
    assert db[BUDGETS].find_one()["reserved_usd"] == 0, "not given back twice"


def test_a_run_keeps_what_every_attempt_cost(db):
    args = dict(
        agent="A11_review_curator",
        task_key="a11:k",
        run_id="run_01K00000000000000000000000",
        project_id="prj_01K00000000000000000000000",
        prompt_version="a11_review_curator.1.1",
        schema_version="1.1.0",
        input_refs=[],
        output_refs=[],
        started=time.monotonic(),
    )
    for cost in (0.01, 0.02):
        result = GatewayResult(outcome="failed", data=None, requested_model="m")
        result.cost_usd = cost
        record_run(db, result=result, outcome="failed", **args)
    record_run(db, result=None, outcome="completed", **args)  # the answer reused from the cache: no new cost
    assert db["ai_agent_runs"].find_one()["estimated_cost_usd"] == pytest.approx(0.03)


# --- jobs ----------------------------------------------------------------------------------------------------------


def test_an_expired_job_asked_to_cancel_is_cancelled(db):
    job, _ = queue.enqueue(db, "collect", "collect:test:cancel", max_attempts=3)
    claimed = queue.claim(db, "w", 60, ["collect"])
    assert claimed is not None
    db["ai_jobs"].update_one(
        {"_id": job["_id"]}, {"$set": {"cancel_requested": True, "lease.expires_at": utcnow() - timedelta(seconds=5)}}
    )
    queue.recover_expired(db)
    assert db["ai_jobs"].find_one({"_id": job["_id"]})["status"] == "cancelled", "never a retry nobody claims"


def test_a_database_stall_does_not_stop_the_heartbeat(db, monkeypatch):
    from app.workers import worker

    real = queue.heartbeat
    stalls = {"n": 0}

    def flaky(*args, **kwargs):
        stalls["n"] += 1
        if stalls["n"] == 1:
            raise RuntimeError("server selection timed out")
        return real(*args, **kwargs)

    monkeypatch.setattr(queue, "heartbeat", flaky)
    seen: list[str] = []

    def handler(db, job, check):
        for _ in range(12):
            time.sleep(0.25)
            seen.append(check())
        return None

    monkeypatch.setitem(worker.HANDLERS, "collect", handler)
    queue.enqueue(db, "collect", "collect:test:beat", max_attempts=1)
    assert worker.run_one(db, "w", 3, ["collect"]) == "completed"
    assert stalls["n"] >= 2 and set(seen) == {"ok"}, "the beat went on after the stall"
    assert threading.active_count() >= 1


# --- API -----------------------------------------------------------------------------------------------------------


def test_webhooks_are_refused_and_a_bad_cursor_is_a_422(api, make_user):
    assert api.post("/v1/webhooks/listening", json={"event": "x"}).status_code == 401
    researcher = sign_in(api, make_user, ["researcher"])
    bad = base64.urlsafe_b64encode(b"[1, 2]").decode()
    response = api.get(f"/v1/projects?cursor={bad}", headers=researcher)
    assert response.status_code == 422 and response.json()["error"]["code"] == "validation_failed"


def test_a_resent_policy_version_is_stored_once(api, db, make_user):
    from .test_policies import version_request

    admin = sign_in(api, make_user, ["admin"])
    headers = {**admin, "Idempotency-Key": "policy-resent-0001"}
    first = api.post("/v1/admin/source-policies", json=version_request("quora"), headers=headers)
    again = api.post("/v1/admin/source-policies", json=version_request("quora"), headers=headers)
    assert first.status_code == 201 and again.json() == first.json()
    assert api.post("/v1/admin/source-policies", json=version_request("quora"), headers=admin).status_code == 422


def test_unknown_project_and_nothing_published_are_told_apart(api, db, fictional):
    assert api.get("/v1/public/projects/no-such-project/insights").json()["error"]["message"] == "No such project"
    slug = db["projects"].find_one({"_id": fictional["Quillon Residences"]})["slug"]
    nothing = api.get(f"/v1/public/projects/{slug}/insights")
    assert nothing.status_code == 404 and nothing.json()["error"]["message"] == "Nothing is published for this project"


def test_the_portfolio_says_whether_a_run_still_works(api, db, settings, make_user, contracts, world):
    run_id = start(db, settings, world["q"])["run_id"]
    db["ai_runs"].update_one({"_id": run_id}, {"$set": {"stage": "analysing", "outcome_note": "Analysis stopped: x"}})
    researcher = sign_in(api, make_user, ["researcher"])
    page = api.get("/v1/projects", headers=researcher).json()
    assert contracts.errors(page, "api.schema.json#/$defs/ProjectPage") == []
    row = next(p for p in page["items"] if p["project"]["id"] == world["q"])
    assert (
        row["latest_run"]["outcome_note"] == "Analysis stopped: x" and row["latest_run"]["content_revision_id"] is None
    )


def test_a_new_source_changes_only_its_own_review_task(db, settings, contracts, fictional, model):
    from app.agents import reviews as a11
    from app.evidence.clusters import cluster_origins

    from .test_agents import text_source

    settings.analysis_mode = "reviews"
    q, _ = analysing_run(db, settings, contracts, fictional)
    for i in range(30):
        text = f"I booked flat {i} in Quillon Residences, Sector 102 last year and the lifts work well."
        text_source(db, contracts, q, f"extra-{i}", text, kind="comment", family="youtube")
    cluster_origins(db.client, db)
    before = {t["key"] for t in a11.build_tasks(db, q)}
    late = "Quillon Residences, Sector 102: the clubhouse opened late but it is good now, say the owners."
    text_source(db, contracts, q, "extra-late", late, kind="comment", family="youtube")
    cluster_origins(db.client, db)
    after = {t["key"] for t in a11.build_tasks(db, q)}
    assert len(before) >= 3, "the sources are spread over several tasks"
    assert len(before - after) <= 1 and len(after - before) <= 2, "the other tasks keep their keys and cached answers"
