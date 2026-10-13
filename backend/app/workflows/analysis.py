"""The analysis workflow (Step 08.5-08.6; docs/04 graph design; docs/05 jobs and checkpoints; D13, D53).

One LangGraph thread per run (thread ID `analysis:<run ID>`), checkpointed in MongoDB
(`lg_checkpoints`, `lg_writes`) after every node. The state holds references and counts only, never source words.

    claims -> findings -> reviews -> conclude -> review (interrupt) -> selected -> format -> end
                                         `-> end (insufficient_evidence)

- claims: A05 over every source task of the project's eligible evidence, A06 over the facts and allegations, then
  the claims are stored (app.agents.verify.store_claims).
- findings: A07 over this run's usable claims, whole aspects packed into a few tasks; findings stored; open agent
  findings that this complete synthesis no longer produces are superseded.
- reviews: A11 over the first-person sources; reviews stored likewise.
- conclude: the run moves to `findings_review` when there is a finding or review to decide, otherwise to
  `insufficient_evidence` (a valid result with no content revision).
- review: an interrupt. The `analyse` job ends `waiting_review` and its lease is released: nothing holds a worker
  while people review.
- selected: runs only when a `resume_after_review` job continues the thread with an event the backend accepted
  (request_resume): a moderator's selection of exact, approved finding and review revisions (findings may be empty
  when reviews are selected, D64). The backend checks the selection again, then moves the run to `formatting`.
- format (Step 10): the content revision is built, checked (deterministic QA, then A09 on model-written text) and
  stored (app.content.service.generate); without a blocking issue the run moves to `final_review`. A model that is
  unavailable or out of budget stops the job like any analysis node; nothing is stored until the draft is complete.

Every node can run again after a crash: model outputs are cached per task, so a finished task is never paid for
twice; records have stable IDs and are written once; stage changes are conditional on the expected stage.
Stops: the model budget (D53) or the run budget reached, or no usable model: the job fails without retry and the
run says why; outputs so far stay cached, so a later analysis continues without paying for them again. A provider
outage: the job retries with backoff. Other task failures (a refusal, malformed output) are counted in the run's
report and the analysis goes on. Cancelling the run cancels its jobs; a running node stops at the next task.
"""

from __future__ import annotations

import hashlib
import json
import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import timedelta
from typing import Any, TypedDict

from langgraph.checkpoint.mongodb import MongoDBSaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt
from pymongo.client_session import ClientSession
from pymongo.database import Database

from app import audit
from app.agents import claims as a05
from app.agents import findings as a07
from app.agents import reviews as a11
from app.agents import verify as a06
from app.agents.gateway import ModelGateway, gateway_for
from app.config import Settings, get_settings
from app.contracts import ContractStore, get_contracts
from app.db import run_in_transaction, utcnow
from app.embeddings.client import Embedder, default_embedder
from app.errors import ApiError
from app.evidence.clusters import KIND as CLUSTER_KIND
from app.jobs import queue
from app.observability import log_event
from app.sources.collection import RUNS, emit
from app.workflows.decisions import finding_problems, review_problems

logger = logging.getLogger(__name__)
CHECKPOINTS, WRITES = "lg_checkpoints", "lg_writes"
ANALYSE, RESUME = "analyse", "resume_after_review"
STOP_CODES = {"budget_exhausted", "access_pending", "no_spend_ledger", "price_unknown", "model_not_found"}
RETRY_CODES = {"provider_unavailable"}


class AnalysisState(TypedDict, total=False):
    run_id: str
    project_id: str
    claims: list[dict[str, Any]]
    findings: list[dict[str, Any]]
    reviews: list[dict[str, Any]]
    report: dict[str, Any]
    outcome: str
    selection: dict[str, Any] | None
    selection_problems: list[str]
    content: dict[str, Any] | None


class AnalysisStopped(Exception):
    """New model work must stop: `retryable` decides whether the job tries again later."""

    def __init__(self, code: str, message: str, *, retryable: bool) -> None:
        super().__init__(f"{code}: {message}")
        self.code, self.message, self.retryable = code, message, retryable


@dataclass
class Context:
    db: Database[dict[str, Any]]
    settings: Settings
    contracts: ContractStore
    gateway: ModelGateway
    embedder: Embedder | None
    check: Callable[[], str]

    def guard(self, run_id: str) -> None:
        """Between tasks: stop when the job was cancelled (check raises), its lease was lost or the run budget is
        spent."""
        if self.check() == "lost":
            raise AnalysisStopped("lease_lost", "another worker owns this job now", retryable=True)
        spent = spent_usd(self.db, run_id)
        if spent >= self.settings.run_budget_usd:
            raise AnalysisStopped(
                "budget_exhausted",
                f"run budget reached: {spent:.4f} of {self.settings.run_budget_usd:.2f} USD",
                retryable=False,
            )


def spent_usd(db: Database[dict[str, Any]], run_id: str) -> float:
    rows = list(
        db["ai_agent_runs"].aggregate(
            [{"$match": {"run_id": run_id}}, {"$group": {"_id": None, "usd": {"$sum": "$estimated_cost_usd"}}}]
        )
    )
    return float(rows[0]["usd"] or 0.0) if rows else 0.0


def _tally(part: dict[str, Any], out: dict[str, Any]) -> None:
    part["tasks"] = part.get("tasks", 0) + 1
    if out["outcome"] == "failed":
        error = out.get("error") or {"code": "unknown", "message": "no error recorded"}
        if error["code"] in STOP_CODES:
            raise AnalysisStopped(error["code"], error["message"], retryable=False)
        if error["code"] in RETRY_CODES:
            raise AnalysisStopped(error["code"], error["message"], retryable=True)
        failed = part.setdefault("failed", {})
        failed[error["code"]] = failed.get(error["code"], 0) + 1
    else:
        outcomes = part.setdefault("outcomes", {})
        outcomes[out["outcome"]] = outcomes.get(out["outcome"], 0) + 1
    dropped = part.setdefault("dropped", {})
    for key, count in (out.get("drops") or out.get("fixes") or {}).items():
        dropped[key] = dropped.get(key, 0) + count


def _project(db: Database[dict[str, Any]], project_id: str) -> tuple[dict[str, Any], dict[str, Any]]:
    project = db["projects"].find_one({"_id": project_id})
    config = db["ai_project_configs"].find_one({"_id": project_id})
    if project is None or config is None:
        raise AnalysisStopped("not_found", "the project or its configuration is missing", retryable=False)
    return project, config


# --- nodes ----------------------------------------------------------------------------------------------------------


def claims_node(ctx: Context, state: AnalysisState) -> dict[str, Any]:
    db, project_id, run_id = ctx.db, state["project_id"], state["run_id"]
    project, config = _project(db, project_id)
    extracted: dict[str, Any] = {}
    drafts: list[dict[str, Any]] = []
    for task in a05.build_tasks(db, project_id):
        ctx.guard(run_id)
        out = a05.extract(db, ctx.gateway, project, config, task, run_id)
        _tally(extracted, out)
        drafts += out["drafts"]
    verified: dict[str, Any] = {}
    verdicts: dict[str, dict[str, Any]] = {}
    for task in a06.build_tasks(db, project_id, drafts, ctx.embedder):
        ctx.guard(run_id)
        out = a06.verify(db, ctx.gateway, project, task, run_id)
        _tally(verified, out)
        verdicts.update(out["verdicts"])
    refs = a06.store_claims(db, ctx.contracts, drafts, verdicts, run_id)
    report = {**state.get("report", {}), "a05": extracted, "a06": verified, "claims": len(refs)}
    report["retrieval"] = "hybrid" if ctx.embedder is not None else "keywords only (embedder not ready)"
    return {"claims": refs, "report": report}


def findings_node(ctx: Context, state: AnalysisState) -> dict[str, Any]:
    db, project_id, run_id = ctx.db, state["project_id"], state["run_id"]
    project, _ = _project(db, project_id)
    usable, left_out = a07.usable_claims(db, project_id, state.get("claims", []))
    part: dict[str, Any] = {"claims_left_out": left_out}
    stored: list[dict[str, Any]] = []
    tasks = a07.build_tasks(db, project_id, usable)
    failed_aspects: set[str] = set()
    for task in tasks:
        ctx.guard(run_id)
        out = a07.synthesise(db, ctx.gateway, project, task, run_id)
        _tally(part, out)
        if out["outcome"] == "failed":
            failed_aspects.update(task["aspects"])
        stored += a07.store_findings(db, ctx.contracts, out["drafts"], run_id)
    report = state.get("report", {})
    upstream_failed = any(report.get(agent, {}).get("failed") for agent in ("a05", "a06"))
    aspects = {a for t in tasks for a in t["aspects"]} if upstream_failed else set(ALL_ASPECTS)
    part["superseded"] = a07.retire_unproduced(db, project_id, sorted(aspects - failed_aspects), stored)
    return {"findings": stored, "report": {**report, "a07": part, "findings": len(stored)}}


def reviews_node(ctx: Context, state: AnalysisState) -> dict[str, Any]:
    db, project_id, run_id = ctx.db, state["project_id"], state["run_id"]
    project, config = _project(db, project_id)
    part: dict[str, Any] = {}
    stored: list[dict[str, Any]] = []
    curated: list[dict[str, Any]] = []
    any_failed = False
    for task in a11.build_tasks(db, project_id):
        ctx.guard(run_id)
        out = a11.curate(db, ctx.gateway, project, config, task, run_id)
        _tally(part, out)
        if out["outcome"] == "failed":
            any_failed = True
            continue
        curated += [{"id": s["source"]["id"], "revision": s["source"]["revision"]} for s in task["sources"]]
        stored += a11.store_reviews(db, ctx.contracts, out["drafts"], run_id)
    part["superseded"] = a11.retire_unproduced(db, project_id, curated if any_failed else None, stored)
    report = {**state.get("report", {}), "a11": part, "reviews": len(stored)}
    return {"reviews": stored, "report": report}


def conclude_node(ctx: Context, state: AnalysisState) -> dict[str, Any]:
    db, run_id = ctx.db, state["run_id"]
    ctx.guard(run_id)
    report = state.get("report", {})
    if state.get("findings") or state.get("reviews"):
        to = "findings_review"
        note = (
            f"{len(state.get('findings', []))} finding(s) and {len(state.get('reviews', []))} review(s) await "
            f"moderator decisions; {report.get('claims', 0)} claim(s) from this analysis"
        )
    else:
        to = "insufficient_evidence"
        note = (
            f"No eligible evidence supports a finding or review: {report.get('claims', 0)} claim(s); "
            "no content revision is created"
        )
    if not move_stage(ctx.contracts, db, run_id, "analysing", to, "system", note, report):
        stage = (db[RUNS].find_one({"_id": run_id}, {"stage": 1}) or {}).get("stage")
        if stage != to:  # not a node running again after a crash: the run moved on (for example, cancelled)
            raise AnalysisStopped("run_moved_on", f"the run is {stage}", retryable=False)
    return {"outcome": to}


def review_node(ctx: Context, state: AnalysisState) -> dict[str, Any]:
    event = interrupt({"run_id": state["run_id"], "waiting_for": "findings_review"})
    return {"selection": event, "selection_problems": []}


def selected_node(ctx: Context, state: AnalysisState) -> dict[str, Any]:
    db, run_id = ctx.db, state["run_id"]
    selection = state.get("selection") or {}
    problems = selection_problems(db, state["project_id"], selection)
    if problems:  # accepted when requested, no longer valid now: wait for another decision
        emit(db, run_id, "error", "findings_review", message=("selection refused: " + "; ".join(problems))[:500])
        return {"selection": None, "selection_problems": problems}
    note = (
        f"Formatting from {len(selection['findings'])} approved finding(s) and {len(selection['reviews'])} approved "
        "review(s)"
    )
    move_stage(ctx.contracts, db, run_id, "findings_review", "formatting", "moderator", note, None)
    return {"selection_problems": []}


def format_node(ctx: Context, state: AnalysisState) -> dict[str, Any]:
    from app.content import service as content  # the content service imports this module (move_stage)

    db, run_id = ctx.db, state["run_id"]
    ctx.guard(run_id)
    run = db[RUNS].find_one({"_id": run_id})
    if run is None or run["stage"] not in ("formatting", "final_review"):
        raise AnalysisStopped("run_moved_on", f"the run is {(run or {}).get('stage')}", retryable=False)
    try:
        out = content.generate(
            db, ctx.contracts, ctx.settings, ctx.gateway, run=run, selection=state["selection"] or {}
        )
    except content.ModelUnavailable as stopped:
        code = stopped.error["code"]
        raise AnalysisStopped(code, stopped.error["message"], retryable=code in RETRY_CODES) from stopped
    qa = out["qa"] or {}
    if out["lifecycle"] == "final_review":
        note = f"Content revision ready for final review ({qa.get('nonblocking_issues', 0)} nonblocking QA note(s))"
        move_stage(ctx.contracts, db, run_id, "formatting", "final_review", "system", note, None)
    else:
        emit(
            db,
            run_id,
            "error",
            "formatting",
            message=f"Draft stored with {qa.get('blocking_issues', 0)} blocking QA issue(s); a moderator edits it",
        )
    return {"content": {"revision_id": out["revision_id"], "lifecycle": out["lifecycle"]}}


ALL_ASPECTS = (
    "connectivity",
    "location",
    "layout",
    "construction_quality",
    "construction_progress",
    "possession",
    "amenities",
    "maintenance",
    "density",
    "parking",
    "water",
    "power",
    "service_management",
    "value_perception",
    "other",
)


def build_graph(ctx: Context, saver: MongoDBSaver) -> Any:
    graph = StateGraph(AnalysisState)
    graph.add_node("claims", lambda s: claims_node(ctx, s))
    graph.add_node("findings", lambda s: findings_node(ctx, s))
    graph.add_node("reviews", lambda s: reviews_node(ctx, s))
    graph.add_node("conclude", lambda s: conclude_node(ctx, s))
    graph.add_node("review", lambda s: review_node(ctx, s))
    graph.add_node("selected", lambda s: selected_node(ctx, s))
    graph.add_node("format", lambda s: format_node(ctx, s))
    graph.add_edge(START, "claims")
    graph.add_edge("claims", "findings")
    graph.add_edge("findings", "reviews")
    graph.add_edge("reviews", "conclude")
    graph.add_conditional_edges(
        "conclude", lambda s: "review" if s.get("outcome") == "findings_review" else END, ["review", END]
    )
    graph.add_edge("review", "selected")
    graph.add_conditional_edges(
        "selected", lambda s: "review" if s.get("selection_problems") else "format", ["review", "format"]
    )
    graph.add_edge("format", END)
    return graph.compile(checkpointer=saver)


def saver_for(db: Database[dict[str, Any]]) -> MongoDBSaver:
    return MongoDBSaver(
        db.client, db_name=db.name, checkpoint_collection_name=CHECKPOINTS, writes_collection_name=WRITES
    )


# --- run stage and selection --------------------------------------------------------------------------------------


def move_stage(
    contracts: ContractStore,
    db: Database[dict[str, Any]],
    run_id: str,
    from_stage: str,
    to_stage: str,
    actor_role: str,
    note: str,
    report: dict[str, Any] | None,
) -> bool:
    """One conditional stage change (a node that runs again finds the stage already moved and changes nothing)."""
    if not contracts.transition_allowed("workflow_stage", from_stage, to_stage, actor_role):
        raise RuntimeError(f"the contract does not allow {from_stage} -> {to_stage} by {actor_role}")
    spent = spent_usd(db, run_id)
    changed = db[RUNS].update_one(
        {"_id": run_id, "stage": from_stage},
        {
            "$set": {
                "stage": to_stage,
                "outcome_note": note[:500],
                "budget.spent_usd": round(spent, 6),
                "updated_at": utcnow(),
            }
        },
    )
    if changed.modified_count:
        emit(db, run_id, "stage_changed", to_stage, message=note[:500])
        details = {"from": from_stage, "to": to_stage}
        if report is not None:
            details["report"] = json.dumps(_flat(report), sort_keys=True)[:500]
        audit.record(db, "run.stage_changed", "run", run_id, audit.SYSTEM_ACTOR, details=details)
    return bool(changed.modified_count)


def _flat(report: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in report.items():
        if isinstance(value, dict):
            for sub, item in _flat(value).items():
                out[f"{key}.{sub}"] = item
        else:
            out[key] = value
    return out


def selection_problems(db: Database[dict[str, Any]], project_id: str, selection: dict[str, Any]) -> list[str]:
    """Why this selection may not start content generation now: every finding and review must be the latest
    revision of this project, approved, and still approvable (decisions.finding_problems/review_problems)."""
    problems: list[str] = []
    if not selection.get("findings") and not selection.get("reviews"):
        return ["nothing selected"]
    for kind, collection, refs, check in (
        ("finding", "ai_findings", selection.get("findings", []), finding_problems),
        ("review", "ai_review_excerpts", selection.get("reviews", []), review_problems),
    ):
        for ref in refs:
            latest = db[collection].find_one({"id": ref["id"]}, sort=[("revision", -1)])
            if latest is None or latest["project_id"] != project_id:
                problems.append(f"{kind} {ref['id']} is not part of this project")
            elif latest["revision"] != ref["revision"]:
                problems.append(f"{kind} {ref['id']} has a newer revision {latest['revision']}")
            elif latest["review_status"] != "approved":
                problems.append(f"{kind} {ref['id']} revision {ref['revision']} is {latest['review_status']}")
            else:
                problems += [f"{kind} {ref['id']}: {p}" for p in check(db, latest)]
    return problems


# --- jobs -----------------------------------------------------------------------------------------------------------


def start_analysis(db: Database[dict[str, Any]], run: dict[str, Any]) -> tuple[dict[str, Any], bool]:
    """Queue the run's analysis once (idempotent by logical key); called when collection finishes."""
    return queue.enqueue(
        db, ANALYSE, f"{ANALYSE}:{run['_id']}:1", run_id=run["_id"], project_id=run["project_id"], max_attempts=4
    )


def inputs_waiting(db: Database[dict[str, Any]], settings: Settings, job: dict[str, Any]) -> str | None:
    """What the analysis should wait for (transcripts still being made, evidence not yet grouped into origins), or
    None. After ANALYSIS_INPUT_WAIT_MINUTES it goes ahead with what is there and says so in the run's report."""
    project_id = job["project_id"]
    media = db["ai_jobs"].count_documents(
        {"kind": "process_media", "project_id": project_id, "status": {"$in": ["queued", "running", "retry_wait"]}}
    )
    unclustered = db["ai_evidence"].count_documents(
        {"project_id": project_id, "origin_cluster": None, "excerpt_text": {"$type": "string"}}
    )
    if unclustered:
        queue.enqueue(db, CLUSTER_KIND, f"{CLUSTER_KIND}:{job['logical_key']}", max_attempts=3)
    if not media and not unclustered:
        return None
    return f"{media} video(s) still being transcribed, {unclustered} evidence span(s) not yet grouped by origin"


def _context(db: Database[dict[str, Any]], check: Callable[[], str]) -> Context:
    settings = get_settings()
    contracts = get_contracts()
    embedder = default_embedder(settings)
    ready = embedder is not None and embedder.ready()
    return Context(db, settings, contracts, gateway_for(db, settings, contracts), embedder if ready else None, check)


def _fail_run_note(db: Database[dict[str, Any]], run_id: str, stopped: AnalysisStopped) -> None:
    note = f"Analysis stopped: {stopped.code}: {stopped.message}"[:500]
    db[RUNS].update_one(
        {"_id": run_id},
        {
            "$set": {
                "outcome_note": note,
                "budget.spent_usd": round(spent_usd(db, run_id), 6),
                "budget.exhausted": stopped.code == "budget_exhausted",
                "updated_at": utcnow(),
            }
        },
    )
    emit(db, run_id, "error", "analysing", message=note)


def thread_of(run_id: str) -> dict[str, Any]:
    return {"configurable": {"thread_id": f"analysis:{run_id}"}}


def _drive(db: Database[dict[str, Any]], job: dict[str, Any], graph: Any, payload: Any) -> str | None:
    """Invoke the graph; a stop becomes the job's failure (and the run's note), an interrupt its pause."""
    config = thread_of(job["run_id"])
    try:
        graph.invoke(payload, config)
    except AnalysisStopped as stopped:
        _fail_run_note(db, job["run_id"], stopped)
        raise queue.JobFailure(stopped.code, stopped.message, retryable=stopped.retryable) from stopped
    snapshot = graph.get_state(config)
    checkpoint_id = str(snapshot.config["configurable"].get("checkpoint_id") or "")
    if snapshot.interrupts:
        raise queue.PausedForReview(checkpoint_id)
    return checkpoint_id or None


def handle_analyse(db: Database[dict[str, Any]], job: dict[str, Any], check: Callable[[], str]) -> str | None:
    """Worker handler for `analyse` jobs: run the graph from the start, or continue it after a crash."""
    run = db[RUNS].find_one({"_id": job["run_id"]})
    if run is None or run["stage"] not in ("analysing", "findings_review"):
        return None  # cancelled, or already past analysis
    if run["stage"] == "findings_review":  # an earlier attempt moved the run, then died before the job said so
        graph = build_graph(_context(db, check), saver_for(db))
        snapshot = graph.get_state(thread_of(run["_id"]))
        if snapshot.interrupts:
            raise queue.PausedForReview(str(snapshot.config["configurable"].get("checkpoint_id") or ""))
        return _drive(db, job, graph, None) if snapshot.next else None
    settings = get_settings()
    waiting = inputs_waiting(db, settings, job)
    if waiting and job["created_at"] > utcnow() - timedelta(minutes=settings.analysis_input_wait_minutes):
        raise queue.Deferred(f"waiting for inputs: {waiting}", 120)
    graph = build_graph(_context(db, check), saver_for(db))
    first = not graph.get_state(thread_of(run["_id"])).values
    payload: Any = {"run_id": run["_id"], "project_id": run["project_id"], "report": {}} if first else None
    if first and waiting:
        payload["report"]["inputs_not_ready"] = waiting
    log_event(logger, "analysis started" if first else "analysis continued", run_id=run["_id"])
    return _drive(db, job, graph, payload)


def handle_resume(db: Database[dict[str, Any]], job: dict[str, Any], check: Callable[[], str]) -> str | None:
    """Worker handler for `resume_after_review` jobs: check the event again, then continue the paused thread (or, after
    a crash part-way, continue from the last checkpoint without delivering the event twice)."""
    run = db[RUNS].find_one({"_id": job["run_id"]})
    if run is not None and run["stage"] == "formatting":  # a crash after the selection was accepted: finish it
        graph = build_graph(_context(db, check), saver_for(db))
        snapshot = graph.get_state(thread_of(run["_id"]))
        return _drive(db, job, graph, None) if snapshot.next else None
    if run is None or run["stage"] != "findings_review":
        return None  # cancelled, or moved on by another decision
    event = job.get("resume_event") or {}
    problems = selection_problems(db, run["project_id"], event)
    if problems:
        raise queue.JobFailure("ineligible_dependency", "; ".join(problems)[:500], retryable=False)
    graph = build_graph(_context(db, check), saver_for(db))
    snapshot = graph.get_state(thread_of(run["_id"]))
    if snapshot.interrupts:
        return _drive(db, job, graph, Command(resume=event))
    return _drive(db, job, graph, None) if snapshot.next else None


def request_resume(
    db: Database[dict[str, Any]], project_id: str, body: dict[str, Any], actor: dict[str, Any]
) -> dict[str, Any]:
    """A moderator's request to generate content from exact approved revisions (ContentRevisionRequest, mode
    generate): checked now, stored with a unique `resume_after_review` job, checked again when the job runs.
    The same selection asked twice is one job (Accepted is returned again)."""
    if actor.get("kind") != "user" or actor.get("role") != "moderator":
        raise ApiError(403, "forbidden", "Only a moderator can continue an analysis after review")
    run = db[RUNS].find_one({"project_id": project_id, "stage": "findings_review"}, sort=[("created_at", -1)])
    if run is None:
        raise ApiError(409, "invalid_transition", "No analysis of this project is waiting for findings review")
    paused = db["ai_jobs"].find_one({"run_id": run["_id"], "kind": ANALYSE, "status": "waiting_review"})
    if paused is None:
        raise ApiError(409, "invalid_transition", "The analysis is not paused for review")
    selection = {
        "findings": sorted(({"id": r["id"], "revision": r["revision"]} for r in body["findings"]), key=json.dumps),
        "reviews": sorted(({"id": r["id"], "revision": r["revision"]} for r in body["reviews"]), key=json.dumps),
    }
    problems = selection_problems(db, project_id, selection)
    if problems:
        raise ApiError(409, "ineligible_dependency", "Cannot generate from this selection: " + "; ".join(problems))
    digest = hashlib.sha256(json.dumps([run["_id"], body["locale"], selection], sort_keys=True).encode()).hexdigest()
    event = {**selection, "locale": body["locale"], "actor": actor, "requested_at": utcnow().isoformat()}

    def write(session: ClientSession) -> dict[str, Any]:
        # One transaction: no worker can claim the job before its event is attached.
        job, created = queue.enqueue(
            db,
            RESUME,
            f"{RESUME}:{run['_id']}:{digest[:32]}",
            run_id=run["_id"],
            project_id=project_id,
            max_attempts=3,
            session=session,
        )
        if created:
            db["ai_jobs"].update_one({"_id": job["_id"]}, {"$set": {"resume_event": event}}, session=session)
            audit.record(
                db,
                "run.resume_requested",
                "run",
                run["_id"],
                actor,
                details={"findings": len(selection["findings"]), "reviews": len(selection["reviews"])},
                session=session,
            )
        return job

    job = run_in_transaction(db.client, write)
    return {"job_id": job["_id"], "run_id": run["_id"], "operation_id": None, "status_path": f"/v1/runs/{run['_id']}"}


def analyse_again(db: Database[dict[str, Any]], run_id: str) -> dict[str, Any]:
    """Operator entry (CLI): after a stop (budget, model access), queue a new `analyse` job for the run. It continues
    the run's thread from its last checkpoint and reuses every cached task output, so nothing is paid twice."""
    run = db[RUNS].find_one({"_id": run_id})
    if run is None or run["stage"] != "analysing":
        raise ValueError(f"run {run_id} is not analysing")
    jobs = list(db["ai_jobs"].find({"run_id": run_id, "kind": ANALYSE}))
    if any(j["status"] not in ("completed", "failed", "cancelled") for j in jobs):
        raise ValueError(f"run {run_id} already has an analysis queued or running")
    job, _ = queue.enqueue(
        db, ANALYSE, f"{ANALYSE}:{run_id}:{len(jobs) + 1}", run_id=run_id, project_id=run["project_id"], max_attempts=4
    )
    return {"job_id": job["_id"], "run_id": run_id}
