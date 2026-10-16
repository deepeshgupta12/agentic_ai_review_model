"""UC-59..UC-63: the analysis workflow (Step 08.5-08.6): LangGraph with MongoDB checkpoints, the findings-review
pause, decisions, resume, restart at every node, budget and model stops, empty corpus and cancellation. A scripted
model answers by agent; fictional projects only, and no model quality is claimed."""

from __future__ import annotations

import json
import re

import pytest

from app.agents import findings as a07
from app.agents import reviews as a11_module
from app.agents.gateway import ModelGateway
from app.agents.spend import SpendLedger
from app.evidence.clusters import cluster_origins
from app.jobs import queue
from app.sources import collection
from app.workers.worker import JobCancelled, run_one
from app.workflows import analysis

from .conftest import sign_in
from .test_agents import COMMENT, POST, setup_project, text_source
from .test_gateway import response

RESEARCHER = {"kind": "user", "user_id": "usr_01K00000000000000000000001", "role": "researcher"}
MODERATOR = {"kind": "user", "user_id": "usr_01K00000000000000000000002", "role": "moderator"}


class ScriptedModel:
    """A fake Anthropic client that answers each agent from the content it is sent (handles included), so a test can
    run the whole graph. `fail` maps an agent to an exception raised on its next call."""

    def __init__(self) -> None:
        self.calls: list[str] = []
        self.answered: list[str] = []
        self.messages = self
        self.fail: dict[str, Exception] = {}
        self.fail_after: int | None = None  # the worker dies during the call after this many answers

    def create(self, **kwargs):
        system = kwargs["system"]  # text, or one cached text block when prompt caching applies (D65)
        agent = re.match(r"You are (A\d\d)", system if isinstance(system, str) else system[0]["text"]).group(1)
        self.calls.append(agent)
        if agent in self.fail:
            raise self.fail.pop(agent)
        if self.fail_after is not None and len(self.answered) == self.fail_after:
            self.fail_after = None
            raise RuntimeError("worker died during a model call")
        lines = [json.loads(x) for x in kwargs["messages"][0]["content"].splitlines() if x.startswith("{")]
        answer = response(getattr(self, agent.lower())(lines[1:]))
        self.answered.append(agent)
        return answer

    @staticmethod
    def a05(items):
        claims = []
        for item in items:
            if item["text"].startswith("Haryana RERA"):
                continue
            sentence = item["text"].split(". ")[0].rstrip(".") + "."
            claims.append(
                {
                    "aspect": "location_connectivity",
                    "aspect_label": None,
                    "claim_type": "opinion",
                    "polarity": "negative",
                    "perspective": "site_visit",
                    "statement": sentence,
                    "evidence_ids": [item["id"]],
                    "observation_date_status": "unknown",
                    "observation_date": None,
                }
            )
        return {"outcome": "completed", "claims": claims}

    @staticmethod
    def a06(items):
        return {"outcome": "insufficient_evidence", "verdicts": []}

    @staticmethod
    def a07(items):
        handles = [i["id"] for i in items]
        wording = "Site visitors are unhappy with what they saw."
        finding = {
            "kind": "con",
            "aspect": "location_connectivity",
            "wording": wording,
            "attribution": "reported_opinion",
            "claim_ids": handles,
            "caveats": [],
        }
        return {"outcome": "completed", "findings": [finding], "insufficiency_note": None}

    @staticmethod
    def a11(items):
        reviews = []
        for source in items:
            span = source["spans"][0]
            reviews.append(
                {
                    "source_id": source["id"],
                    "evidence_ids": [span["id"]],
                    "perspective": "owner_awaiting_possession",
                    "polarity": "positive",
                    "aspects": ["maintenance_facility_mgmt"],
                    "rendering": "verbatim",
                    "text": span["text"],
                    "translation_note": None,
                }
            )
        return {"outcome": "completed", "reviews": reviews}

    @staticmethod
    def a08(items):
        """Page blocks: one attributed item per approved finding, citing it and its claims (Step 10)."""
        findings = [i for i in items if i["id"].startswith("f")]
        blocks = {"pro": [], "con": []}
        for finding in findings:
            if finding["kind"] in blocks:
                text = "Some buyers say: " + finding["wording"]
                blocks[finding["kind"]].append(
                    {"text": text, "caveat": None, "finding_ids": [finding["id"]], "claim_ids": finding["claims"]}
                )
        return {
            "outcome": "completed",
            "heading": "",  # the backend replaces a heading that does not name the project
            "overview": {
                "text": "Some buyers discuss " + ", ".join(sorted({f["aspect"] for f in findings})) + ".",
                "caveat": None,
                "finding_ids": [f["id"] for f in findings],
                "claim_ids": [c for f in findings for c in f["claims"]],
            },
            "advantages": blocks["pro"],
            "considerations": blocks["con"],
            "questions": [],
            "coverage_note": "",
            "metadata": {"title": "What buyers say", "description": "Reviewed points from public discussion."},
        }

    @staticmethod
    def a09(items):
        return {"outcome": "completed", "issues": []}


@pytest.fixture
def model(monkeypatch, settings):
    """The full analysis (claims, findings and reviews); the reviews-only default (D68) is tested on its own. The
    fixture's texts are shorter than a published review (D69), and its two sources form one A11 task (the tests count
    model calls; the bucket packing of D70 is tested in test_audit_fixes)."""
    settings.analysis_mode = "full"
    settings.review_words_min = 1
    monkeypatch.setattr(a11_module, "BUCKETS", 1)
    client = ScriptedModel()
    monkeypatch.setattr(analysis, "get_settings", lambda: settings)
    monkeypatch.setattr(analysis, "default_embedder", lambda _s: None)
    monkeypatch.setattr(collection, "get_settings", lambda: settings)

    def gateway(db, s, contracts):
        return ModelGateway(s, contracts, client=client, sleep=lambda _s: None, ledger=SpendLedger(db, s))

    monkeypatch.setattr(analysis, "gateway_for", gateway)
    return client


def analysing_run(db, settings, contracts, fictional, *, evidence=True):
    """A run of the fictional Quillon project whose collection is done (no connector has a credential in tests), so
    its `analyse` job is queued; with a post and a YouTube comment as eligible evidence."""
    q, _, _ = setup_project(db, contracts, fictional, status="under_construction")
    if evidence:
        text_source(db, contracts, q, "post", POST)
        text_source(db, contracts, q, "comment-1", COMMENT, kind="comment", family="youtube")
        cluster_origins(db.client, db)
    accepted = collection.start_run(
        db.client, db, settings, q, {"window_days": 30, "connectors": ["brave_search"]}, RESEARCHER
    )
    run = db["ai_runs"].find_one({"_id": accepted["run_id"]})
    assert run["stage"] == "analysing"
    return q, run


def work(db):
    statuses = []
    while (status := run_one(db, "test-worker", 60)) is not None:
        statuses.append(status)
    return statuses


def job(db, run_id, kind="analyse"):
    return db["ai_jobs"].find_one({"run_id": run_id, "kind": kind}, sort=[("created_at", -1)])


# --- UC-59: pause at findings review ------------------------------------------------------------------------------


def test_analysis_pauses_for_review_and_releases_its_worker(db, settings, contracts, fictional, model):
    _, run = analysing_run(db, settings, contracts, fictional)
    assert work(db) == ["waiting_review"]
    paused = job(db, run["_id"])
    assert paused["status"] == "waiting_review" and paused["lease"] is None and paused["checkpoint_id"]
    run = db["ai_runs"].find_one({"_id": run["_id"]})
    assert run["stage"] == "findings_review" and "await moderator decisions" in run["outcome_note"]
    assert model.calls == ["A05", "A05", "A07", "A11"], "facts go to A06; these opinions need no verification"
    assert db["ai_findings"].count_documents({"review_status": "pending"}) == 1
    assert db["ai_review_excerpts"].count_documents({"review_status": "pending"}) == 2, "the post and the comment"
    assert db["lg_checkpoints"].count_documents({}) >= 5
    assert db["ai_findings"].count_documents({"review_status": "approved"}) == 0, "models never approve"
    assert db["ai_review_decisions"].count_documents({}) == 0
    checkpoint_text = json.dumps([str(d) for d in db["lg_checkpoints"].find()])
    assert "approach road" not in checkpoint_text, "the graph state holds references, never source words"


# --- UC-60: decisions and resume ----------------------------------------------------------------------------------


def test_decisions_name_the_exact_revision_and_come_from_a_moderator_session(
    api, make_user, db, settings, contracts, fictional, model
):
    q, _ = analysing_run(db, settings, contracts, fictional)
    work(db)
    finding = db["ai_findings"].find_one({"project_id": q})
    review = db["ai_review_excerpts"].find_one({"project_id": q})
    researcher = sign_in(api, make_user, ["researcher"])
    body = {"revision": 1, "action": "approve", "reason": None}
    assert api.post(f"/v1/findings/{finding['id']}/decisions", json=body, headers=researcher).status_code == 403
    moderator = sign_in(api, make_user, ["moderator"])
    stale = api.post(f"/v1/findings/{finding['id']}/decisions", json={**body, "revision": 2}, headers=moderator)
    assert stale.status_code == 409 and stale.json()["error"]["code"] == "version_conflict"
    by_aspect = api.get(f"/v1/projects/{q}/sources?aspect=location_connectivity", headers=moderator).json()["items"]
    assert {i["source_kind"] for i in by_aspect} == {"forum_post", "comment"}, "aspects come from the claims"
    assert all(i["aspects"] == ["location_connectivity"] for i in by_aspect)
    assert api.get(f"/v1/projects/{q}/sources?aspect=safety_security", headers=moderator).json()["items"] == []
    listed = api.get(f"/v1/projects/{q}/findings", headers=moderator).json()["items"]
    assert listed[0]["eligible"] and listed[0]["claims"] and listed[0]["evidence"]
    assert contracts.errors(listed[0], "api.schema.json#/$defs/FindingView") == []
    decided = api.post(f"/v1/findings/{finding['id']}/decisions", json=body, headers=moderator)
    assert decided.status_code == 200 and decided.json()["actor"]["role"] == "moderator"
    assert contracts.errors(decided.json(), "content.schema.json#/$defs/ReviewDecision") == []
    again = api.post(f"/v1/findings/{finding['id']}/decisions", json=body, headers=moderator)
    assert again.status_code == 409 and again.json()["error"]["code"] == "invalid_transition"
    reviews = api.get(f"/v1/projects/{q}/review-excerpts", headers=moderator).json()["items"]
    assert reviews[0]["rendering_check"] == "matches_original"
    assert contracts.errors(reviews[0], "api.schema.json#/$defs/ReviewExcerptView") == []
    db["ai_review_excerpts"].update_one(
        {"_id": review["_id"]}, {"$set": {"consistency_flags": ["occupancy_before_possession"]}}
    )
    flagged = api.post(f"/v1/review-excerpts/{review['id']}/decisions", json=body, headers=moderator)
    assert flagged.status_code == 409 and flagged.json()["error"]["code"] == "ineligible_dependency"
    rejected = api.post(
        f"/v1/review-excerpts/{review['id']}/decisions",
        json={"revision": 1, "action": "reject", "reason": "claims to live in a project not yet handed over"},
        headers=moderator,
    )
    assert rejected.status_code == 200


def approve_all(db, q):
    for collection_name in ("ai_findings", "ai_review_excerpts"):
        db[collection_name].update_many({"project_id": q}, {"$set": {"review_status": "approved"}})


def selection(db, q):
    return {
        "mode": "generate",
        "locale": "en-IN",
        "findings": [{"id": f["id"], "revision": f["revision"]} for f in db["ai_findings"].find({"project_id": q})],
        "reviews": [
            {"id": r["id"], "revision": r["revision"]} for r in db["ai_review_excerpts"].find({"project_id": q})
        ],
    }


def test_only_a_checked_moderator_selection_resumes_the_graph(db, settings, contracts, fictional, model):
    q, run = analysing_run(db, settings, contracts, fictional)
    work(db)
    with pytest.raises(Exception, match="pending"):
        analysis.request_resume(db, q, selection(db, q), MODERATOR)
    approve_all(db, q)
    with pytest.raises(Exception, match="moderator"):
        analysis.request_resume(db, q, selection(db, q), RESEARCHER)
    accepted = analysis.request_resume(db, q, selection(db, q), MODERATOR)
    assert analysis.request_resume(db, q, selection(db, q), MODERATOR) == accepted, "the same request is one job"
    resume = db["ai_jobs"].find_one({"_id": accepted["job_id"]})
    assert resume["kind"] == "resume_after_review" and resume["resume_event"]["actor"] == MODERATOR
    assert work(db) == ["completed"]
    run = db["ai_runs"].find_one({"_id": run["_id"]})
    assert run["stage"] == "final_review" and "ready for final review" in run["outcome_note"]
    assert model.calls == ["A05", "A05", "A07", "A11", "A08", "A09"], "resuming writes and checks the page only"
    revision = db["ai_content_revisions"].find_one({"_id": run["content_revision_id"]})
    assert revision["lifecycle"] == "final_review" and revision["qa"]["blocking_issues"] == 0


def test_a_selection_that_changed_after_the_request_is_refused_and_the_graph_stays_paused(
    db, settings, contracts, fictional, model
):
    q, run = analysing_run(db, settings, contracts, fictional)
    work(db)
    approve_all(db, q)
    accepted = analysis.request_resume(db, q, selection(db, q), MODERATOR)
    db["ai_sources"].update_many({"source_kind": "forum_post"}, {"$set": {"lifecycle": "withdrawn"}})
    assert work(db) == ["failed"]
    failed = db["ai_jobs"].find_one({"_id": accepted["job_id"]})
    assert failed["error"]["code"] == "ineligible_dependency" and not failed["error"]["retryable"]
    assert db["ai_runs"].find_one({"_id": run["_id"]})["stage"] == "findings_review"
    assert job(db, run["_id"])["status"] == "waiting_review", "the analysis thread is still paused at the review"


# --- UC-61: restart at every durable node -------------------------------------------------------------------------


def clean_result(db, q):
    return (
        sorted(db["ai_claims"].distinct("_id")),
        sorted(db["ai_findings"].distinct("_id")),
        sorted(db["ai_review_excerpts"].distinct("_id")),
    )


CRASHES = [
    "before_claims",
    "mid_claims",
    "before_findings",
    "after_findings_written",
    "before_reviews",
    "after_reviews_written",
    "after_stage_moved",
    "after_pause",
]


@pytest.mark.parametrize("crash", CRASHES)
def test_a_crash_at_any_node_recovers_without_duplicates_or_paying_twice(
    db, settings, contracts, fictional, model, monkeypatch, crash
):
    """The worker dies at each durable point; the retried job finishes with the same records and every answered
    model call paid once."""
    q, run = analysing_run(db, settings, contracts, fictional)
    crashed = {"done": False}

    def once(message):
        if not crashed["done"]:
            crashed["done"] = True
            raise RuntimeError(message)

    def wrap(name, after):
        original = getattr(analysis, f"{name}_node")

        def node(ctx, state):
            if not after:
                once(f"worker died before {name}")
            result = original(ctx, state)
            if after:
                once(f"worker died after {name} wrote its records")
            return result

        monkeypatch.setattr(analysis, f"{name}_node", node)

    if crash == "mid_claims":  # the second A05 call dies with the worker; the first answer is already kept
        model.fail_after, crashed["done"] = 1, True
    elif crash == "after_pause":  # the graph paused; the worker died before the job recorded the pause
        real = queue.pause_for_review

        def lost(*args, **kwargs):
            once("worker died before recording the pause")
            return real(*args, **kwargs)

        monkeypatch.setattr(queue, "pause_for_review", lost)
    else:
        when, _, name = crash.partition("_")
        name = {"stage_moved": "conclude", "findings_written": "findings", "reviews_written": "reviews"}.get(name, name)
        wrap(name, after=when == "after")
    try:
        statuses = work(db)
    except RuntimeError:  # the worker process itself died: its lease expires and the job is recovered
        db["ai_jobs"].update_many({"status": "running"}, {"$currentDate": {"lease.expires_at": True}})
        statuses = []
    if not statuses or statuses[-1] != "waiting_review":  # the retry waits for its backoff; let it run now
        db["ai_jobs"].update_many({"status": "retry_wait"}, {"$currentDate": {"next_attempt_at": True}})
        statuses += work(db)
    assert statuses[-1] == "waiting_review" and crashed["done"]
    assert job(db, run["_id"])["status"] == "waiting_review"
    assert db["ai_runs"].find_one({"_id": run["_id"]})["stage"] == "findings_review"
    assert sorted(model.answered) == ["A05", "A05", "A07", "A11"], "cached task outputs: nothing is paid twice"
    assert len(model.calls) == len(model.answered) + (crash == "mid_claims")
    claims, findings, reviews = clean_result(db, q)
    assert (len(claims), len(findings), len(reviews)) == (2, 1, 2), "stable IDs: nothing written twice"
    assert db["ai_run_events"].count_documents({"run_id": run["_id"], "stage": "findings_review"}) == 1


@pytest.mark.parametrize("after", [False, True])
def test_a_crash_while_resuming_moves_the_run_once(db, settings, contracts, fictional, model, monkeypatch, after):
    q, run = analysing_run(db, settings, contracts, fictional)
    work(db)
    approve_all(db, q)
    analysis.request_resume(db, q, selection(db, q), MODERATOR)
    original, crashed = analysis.selected_node, {"done": False}

    def node(ctx, state):
        if not after and not crashed["done"]:
            crashed["done"] = True
            raise RuntimeError("worker died before the selection was applied")
        result = original(ctx, state)
        if after and not crashed["done"]:
            crashed["done"] = True
            raise RuntimeError("worker died after the run moved to formatting")
        return result

    monkeypatch.setattr(analysis, "selected_node", node)
    assert work(db) == ["retry_wait"]
    db["ai_jobs"].update_many({"status": "retry_wait"}, {"$currentDate": {"next_attempt_at": True}})
    assert work(db) == ["completed"]
    assert db["ai_runs"].find_one({"_id": run["_id"]})["stage"] == "final_review"
    moved = {"run_id": run["_id"], "stage": "formatting", "type": "stage_changed"}
    assert db["ai_run_events"].count_documents(moved) == 1, "moved once (a crash also says it is retried, D70)"
    assert db["ai_content_revisions"].count_documents({"project_id": q}) == 1, "one revision however often it resumes"


# --- UC-62: explicit stops -----------------------------------------------------------------------------------------


def test_budget_exhaustion_stops_the_analysis_visibly_and_a_new_budget_continues_it(
    db, settings, contracts, fictional, model
):
    _, run = analysing_run(db, settings, contracts, fictional)
    settings.model_budget_usd = 0.0
    assert work(db) == ["failed"]
    stopped = job(db, run["_id"])
    assert stopped["error"]["code"] == "budget_exhausted" and not stopped["error"]["retryable"]
    run_doc = db["ai_runs"].find_one({"_id": run["_id"]})
    assert run_doc["stage"] == "analysing" and run_doc["budget"]["exhausted"]
    assert run_doc["outcome_note"].startswith("Analysis stopped: budget_exhausted")
    assert model.calls == [], "no call is made once the budget is spent"
    settings.model_budget_usd = 2.0
    analysis.analyse_again(db, run["_id"])
    assert work(db) == ["waiting_review"]
    assert db["ai_runs"].find_one({"_id": run["_id"]})["stage"] == "findings_review"


def test_an_unavailable_model_is_an_explicit_outcome_not_a_silent_skip(db, settings, contracts, fictional, monkeypatch):
    monkeypatch.setattr(analysis, "get_settings", lambda: settings)
    monkeypatch.setattr(analysis, "default_embedder", lambda _s: None)
    _, run = analysing_run(db, settings, contracts, fictional)
    assert work(db) == ["failed"]
    stopped = job(db, run["_id"])
    assert stopped["error"]["code"] == "access_pending" and not stopped["error"]["retryable"]
    assert "access_pending" in db["ai_runs"].find_one({"_id": run["_id"]})["outcome_note"]


def test_a_provider_outage_retries_the_job(db, settings, contracts, fictional, model):
    import anthropic

    from .test_gateway import api_error

    settings.model_max_attempts = 1
    _, run = analysing_run(db, settings, contracts, fictional)
    model.fail["A05"] = api_error(anthropic.InternalServerError, 503)
    assert work(db) == ["retry_wait"]
    assert job(db, run["_id"])["error"]["code"] == "provider_unavailable"


def test_an_empty_corpus_ends_insufficient_evidence_with_no_model_call(db, settings, contracts, fictional, model):
    _, run = analysing_run(db, settings, contracts, fictional, evidence=False)
    assert work(db) == ["completed"]
    run = db["ai_runs"].find_one({"_id": run["_id"]})
    assert run["stage"] == "insufficient_evidence" and run["content_revision_id"] is None
    assert "no content revision" in run["outcome_note"] and model.calls == []
    assert contracts.errors(collection.run_view(run), "operations.schema.json#/$defs/WorkflowRun") == []


# --- UC-63: cancellation ------------------------------------------------------------------------------------------


def test_cancelling_stops_at_the_next_task_and_keeps_what_was_done(db, settings, contracts, fictional, model):
    _ = analysing_run(db, settings, contracts, fictional)
    claimed = queue.claim(db, "test-worker", 60)
    asked = {"n": 0}

    def check():
        asked["n"] += 1
        if asked["n"] > 1:  # cancelled after the first task
            raise JobCancelled
        return "ok"

    with pytest.raises(JobCancelled):
        analysis.handle_analyse(db, claimed.job, check)
    assert model.calls == ["A05"] and db["ai_agent_outputs"].count_documents({}) == 1, "the first output is kept"


def test_a_paused_run_can_be_cancelled_and_then_never_resumes(db, settings, contracts, fictional, model):
    q, run = analysing_run(db, settings, contracts, fictional)
    work(db)
    approve_all(db, q)
    collection.cancel_run(db.client, db, contracts, run["_id"], "duplicate run", RESEARCHER)
    assert job(db, run["_id"])["status"] == "cancelled"
    with pytest.raises(Exception, match="waiting for findings review"):
        analysis.request_resume(db, q, selection(db, q), MODERATOR)


def test_the_finding_attribution_rule_is_shared_by_synthesis_and_approval():
    verified = {"verification": {"status": "verified"}}
    opinion = {"verification": {"status": "not_applicable"}}
    assert a07.attribution_for([verified], 1) == "verified_fact"
    assert a07.attribution_for([verified, opinion], 1) == "reported_opinion"
    assert a07.attribution_for([verified, opinion], 2) == "mixed"
    assert a07.attribution_for([opinion], 3) == "reported_opinion"


def test_the_analysis_checks_pass_on_good_data_and_catch_an_approval_nobody_made(
    db, settings, contracts, fictional, model
):
    from app.workflows.verify import verify_analysis

    q, _ = analysing_run(db, settings, contracts, fictional)
    work(db)
    rows = verify_analysis(db, contracts, settings)
    assert all(r["ok"] for r in rows), [r for r in rows if not r["ok"]]
    assert {r["looked_at"] for r in rows if r["check"].startswith("every claim")} == {2}
    db["ai_findings"].update_one({"project_id": q}, {"$set": {"review_status": "approved"}})
    broken = {r["check"] for r in verify_analysis(db, contracts, settings) if not r["ok"]}
    assert broken == {"every approval is a person's decision on that exact revision; no flagged approval"}


def test_the_sample_sheet_lists_claims_findings_and_reviews_with_their_words_and_empty_verdicts(
    db, settings, contracts, fictional, model
):
    import csv
    import io

    from app.workflows.sample import COLUMNS, sample_csv

    analysing_run(db, settings, contracts, fictional)
    work(db)
    text = sample_csv(db)
    assert text.startswith("﻿"), "a byte-order mark so spreadsheets read Hindi"
    rows = list(csv.reader(io.StringIO(text.lstrip("﻿"))))
    assert rows[0] == COLUMNS
    items = [r[2] for r in rows[1:]]
    assert items.count("claim") == 2 and items.count("finding") == 1 and items.count("review") == 2
    assert all(r[-3:] == ["", "", ""] for r in rows[1:]), "the verdict columns are for the reviewer"
    assert all(r[11] and r[12].startswith("https://") for r in rows[1:]), "every row shows its words and source"
