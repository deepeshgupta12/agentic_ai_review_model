"""Collection runs (WorkflowRun; Step 05.2-05.7; journeys J02, J16).

A run belongs to one project. Starting it creates the run (stage `collecting`) and one durable `collect` job per
connector group, so one provider's outage never stops the others:
- `web`: Brave discovery, then the web reader for hits whose host policy allows reading;
- `youtube_data_api`: video search and metadata, then comments on videos whose match is accepted.
Connectors without a credential (or an adapter) never run and are reported `access_pending`. Each page's
records are stored before its cursor moves, in one transaction, so a crash replays the page harmlessly.
Coverage per connector is written to the run as each group finishes; when every group is done the run moves
to `analysing` and its `analyse` job is queued (app.workflows.analysis, Step 08). Cancelling stops the jobs
cooperatively and keeps what was found.
"""

from __future__ import annotations

import json
import logging
import re
import time
from datetime import timedelta
from typing import Any
from urllib.parse import urlsplit

from pymongo import MongoClient
from pymongo.client_session import ClientSession
from pymongo.database import Database
from ulid import ULID

from app import audit
from app.agents.gateway import ModelGateway, gateway_for
from app.config import Settings, get_settings
from app.connectors.base import Page, ProviderError
from app.connectors.portal_reviews import page_reviews, review_item
from app.connectors.reddit import comment_item as reddit_comment_item
from app.connectors.reddit import post_item as reddit_post_item
from app.connectors.registry import build
from app.connectors.web import FetchOutcome, WebFetch
from app.contracts import ContractStore, get_contracts, to_view
from app.db import run_in_transaction, utcnow
from app.errors import ApiError
from app.identity.links import ACTIVE_STATUSES
from app.identity.queries import build_query_plan
from app.identity.service import identify_in_context, identify_metadata, identify_source
from app.identity.text import normalise_text
from app.ids import new_id
from app.jobs import queue
from app.jobs.queue import JobCancelled, JobLost
from app.observability import log_event
from app.sources import policies, state
from app.sources.store import Item, Stored, store_item, withdrawn_on_request

logger = logging.getLogger(__name__)
RUNS = "ai_runs"
EVENTS = "ai_run_events"
GROUPS = {
    "web": ("brave_search", "web_fetch"),
    "youtube_data_api": ("youtube_data_api",),
    "registry": ("harera_registry",),  # Step 08 (D53): dated primary records for verification
    "instagram": ("instagram_public",),  # Step 08 (D54): public posts through Scrapfly
    "reddit": ("reddit_public",),  # D67, D68: public threads through the PullPush archive
}
TERMINAL_JOB = {"completed", "failed", "cancelled"}
HELPER_CONNECTORS = {"firecrawl", "playwright_fetch"}  # used inside the web reader, never run as sources
# Live coverage while a run collects: a planned source waits as "queued", then shows what it is doing ("in progress:")
# and its counts so far, at most once every PROGRESS_SECONDS per source; its final entry replaces that.
QUEUED = "queued"
IN_PROGRESS = "in progress: "
PROGRESS_SECONDS = 3.0
HOST_TIMEOUTS = 2  # a host that timed out this often is not asked again in the same job
SEARCHES = "ai_run_searches"  # each finished search of a run, so a retried job reuses it instead of paying again


def run_view(doc: dict[str, Any]) -> dict[str, Any]:
    view = to_view(doc)
    assert view is not None
    return view


def emit(
    db: Database[dict[str, Any]],
    run_id: str,
    kind: str,
    stage: str,
    *,
    coverage: dict[str, Any] | None = None,
    message: str | None = None,
    session: ClientSession | None = None,
) -> None:
    db[EVENTS].insert_one(
        {
            "_id": str(ULID()),
            "run_id": run_id,
            "type": kind,
            "at": utcnow(),
            "stage": stage,
            "coverage": coverage,
            "message": message,
        },
        session=session,
    )


def _registry(settings: Settings) -> dict[str, dict[str, Any]]:
    data = json.loads((settings.seed_dir / "connectors.json").read_text(encoding="utf-8"))
    return {c["id"]: c for c in data["connectors"]}


def _coverage(connector_id: str, status: str, note: str | None, **counts: int) -> dict[str, Any]:
    entry = {
        "connector_id": connector_id,
        "status": status,
        "attempted_queries": 0,
        "fetched": 0,
        "matched": 0,
        "analysed": 0,
        "metadata_only": 0,
        "last_success_at": None,
        "note": note,
    }
    entry.update(counts)
    return entry


def start_run(
    client: MongoClient[dict[str, Any]],
    db: Database[dict[str, Any]],
    settings: Settings,
    project_id: str,
    body: dict[str, Any],
    actor: dict[str, Any],
    via: str = "api",
) -> dict[str, Any]:
    """Create the run and its collect jobs (RunRequest -> Accepted). `via` records the entry point (api or cli)."""
    project = db["projects"].find_one({"_id": project_id})
    config = db["ai_project_configs"].find_one({"_id": project_id})
    if project is None or config is None:
        raise ApiError(404, "not_found", "No such project")
    enabled = [s["connector_id"] for s in config["sources"] if s["enabled"]]
    chosen = body["connectors"] or enabled
    unknown = [c for c in chosen if c not in enabled]
    if unknown:
        raise ApiError(
            422,
            "validation_failed",
            "Connectors are not enabled for this project",
            fields=[{"path": "connectors", "message": ", ".join(unknown)}],
        )
    working = db[RUNS].find_one(
        {
            "project_id": project_id,
            "$or": [
                {"stage": "collecting"},
                {"stage": "analysing", "outcome_note": {"$not": {"$regex": "^Analysis stopped"}}},
            ],
        },
        {"_id": 1},
    )
    if working is not None:  # never two paid collections of one project at once (audit, 14 Oct 2026)
        raise ApiError(
            409,
            "invalid_transition",
            f"Run {working['_id']} of this project is still working; wait for it or cancel it first",
        )
    window_days = body["window_days"] or config["refresh"]["lookback_days"]
    # Helpers are not sources of their own: Firecrawl renders pages for the web reader (D62), and its pages are counted
    # under web_fetch. Listing them as run sources showed a working Firecrawl key as "access pending".
    chosen = [c for c in chosen if c not in HELPER_CONNECTORS]
    if "brave_search" in chosen and "web_fetch" not in chosen and "web_fetch" in enabled:
        chosen = [*chosen, "web_fetch"]  # discovery hits are read by the web reader
    coverage, groups = [], []
    runnable = {c for c in chosen if build(c, db, settings) is not None}
    for connector_id in chosen:
        if connector_id == "harera_registry" and settings.analysis_mode == "reviews":
            # D68: a reviews-only analysis uses no registry records, so the registries are not read (and cost nothing)
            coverage.append(
                _coverage(connector_id, "unavailable", "not run: reviews-only analysis takes no registry records (D68)")
            )
            continue
        if connector_id not in runnable:
            coverage.append(_coverage(connector_id, "access_pending", "no credential or adapter configured; not run"))
        elif connector_id == "web_fetch" and "brave_search" not in runnable:
            coverage.append(_coverage(connector_id, "access_pending", "not run: no discovery source (brave_search)"))
        else:
            coverage.append(_coverage(connector_id, "partial", QUEUED))
    for group, members in GROUPS.items():
        if any(c["connector_id"] in members and c["status"] == "partial" for c in coverage):
            groups.append(group)
    now = utcnow()
    run_id = new_id("run")
    run = {
        "_id": run_id,
        "project_id": project_id,
        "stage": "collecting",
        "trigger": "manual",
        "requested_by": actor,
        "window": {"from": now - timedelta(days=window_days), "to": now},
        "coverage": coverage,
        "budget": {"max_usd": float(settings.run_budget_usd), "spent_usd": 0.0, "exhausted": False},
        "content_revision_id": None,
        "outcome_note": None,
        "created_at": now,
        "updated_at": now,
    }

    def write(session: ClientSession) -> list[str]:
        db[RUNS].insert_one(run, session=session)
        emit(
            db, run_id, "stage_changed", "collecting", message=f"collecting with {len(groups)} job(s)", session=session
        )
        audit.record(
            db,
            "run.started",
            "run",
            run_id,
            actor,
            details={"groups": ",".join(groups) or "none", "via": via},
            session=session,
        )
        job_ids = []
        for group in groups:
            job, _ = queue.enqueue(
                db,
                "collect",
                f"collect:{run_id}:{group}",
                run_id=run_id,
                project_id=project_id,
                max_attempts=3,
                session=session,
            )
            job_ids.append(job["_id"])
        return job_ids

    job_ids = run_in_transaction(client, write)
    if not groups:
        finish_if_done(client, db, run_id)
    return {
        "job_id": job_ids[0] if job_ids else None,
        "run_id": run_id,
        "operation_id": None,
        "status_path": f"/v1/runs/{run_id}",
    }


def update_coverage(
    db: Database[dict[str, Any]], run_id: str, entry: dict[str, Any], session: ClientSession | None = None
) -> None:
    db[RUNS].update_one(
        {"_id": run_id, "coverage.connector_id": entry["connector_id"]},
        {"$set": {"coverage.$": entry, "updated_at": utcnow()}},
        session=session,
    )
    run = db[RUNS].find_one({"_id": run_id}, {"stage": 1}, session=session)
    emit(db, run_id, "coverage_updated", run["stage"] if run else "collecting", coverage=entry, session=session)


def finish_if_done(
    client: MongoClient[dict[str, Any]], db: Database[dict[str, Any]], run_id: str, exclude_job: str | None = None
) -> bool:
    """collecting -> analysing (system) once every collect job of the run has finished."""
    open_jobs = db["ai_jobs"].count_documents(
        {
            "run_id": run_id,
            "kind": "collect",
            "status": {"$nin": sorted(TERMINAL_JOB)},
            **({"_id": {"$ne": exclude_job}} if exclude_job else {}),
        }
    )
    if open_jobs:
        return False
    failed = db["ai_jobs"].find_one({"run_id": run_id, "kind": "collect", "status": "failed"}, {"error": 1})
    finalise_open_coverage(
        db,
        run_id,
        None,
        f"its job failed ({((failed or {}).get('error') or {}).get('code', 'unknown')})"
        if failed
        else "its job ended before it finished",
    )
    contracts = get_contracts()
    if not contracts.transition_allowed("workflow_stage", "collecting", "analysing", "system"):
        raise RuntimeError("the contract no longer allows collecting -> analysing")
    now = utcnow()
    result = db[RUNS].update_one(
        {"_id": run_id, "stage": "collecting"},
        {
            "$set": {
                "stage": "analysing",
                "updated_at": now,
                "outcome_note": "Collection finished; analysis queued",
            }
        },
    )
    if result.modified_count:
        from app.workflows.analysis import start_analysis  # the workflow imports this module

        emit(db, run_id, "stage_changed", "analysing", message="collection finished")
        emit(db, run_id, "completed", "analysing", message="collection stage complete")
        run = db[RUNS].find_one({"_id": run_id})
        assert run is not None
        start_analysis(db, run)
    return bool(result.modified_count)


def cancel_run(
    client: MongoClient[dict[str, Any]],
    db: Database[dict[str, Any]],
    contracts: ContractStore,
    run_id: str,
    reason: str,
    actor: dict[str, Any],
) -> dict[str, Any]:
    run = db[RUNS].find_one({"_id": run_id})
    if run is None:
        raise ApiError(404, "not_found", "No such run")
    if not contracts.transition_allowed("workflow_stage", run["stage"], "cancelled", actor["role"]):
        raise ApiError(409, "invalid_transition", f"A run that is {run['stage']} cannot be cancelled")
    moved = db[RUNS].update_one(
        {"_id": run_id, "stage": run["stage"]},
        {"$set": {"stage": "cancelled", "updated_at": utcnow(), "outcome_note": f"Cancelled: {reason}"}},
    )
    if moved.modified_count != 1:  # the run moved on meanwhile: nothing was cancelled
        raise ApiError(409, "version_conflict", "The run changed while cancelling; reload it")
    for job in db["ai_jobs"].find({"run_id": run_id, "status": {"$nin": sorted(TERMINAL_JOB)}}):
        queue.cancel(db, job["_id"])
    finalise_open_coverage(db, run_id, None, "the run was cancelled")
    emit(db, run_id, "stage_changed", "cancelled", message=f"cancelled: {reason}")
    audit.record(db, "run.cancelled", "run", run_id, actor, details={"reason": reason[:300]})
    return {"job_id": None, "run_id": run_id, "operation_id": None, "status_path": f"/v1/runs/{run_id}"}


# --- The collect job ---------------------------------------------------------------------------------------


class Collector:
    def __init__(
        self,
        client: MongoClient[dict[str, Any]],
        db: Database[dict[str, Any]],
        job: dict[str, Any],
        check: Any,
        settings: Settings | None = None,
        contracts: ContractStore | None = None,
    ) -> None:
        self.client, self.db, self.job, self.check = client, db, job, check
        self.settings = settings or get_settings()
        self.contracts = contracts or get_contracts()
        self.run_id = job["run_id"]
        self.project_id = job["project_id"]
        run = db[RUNS].find_one({"_id": self.run_id}, {"coverage": 1}) or {"coverage": []}
        # Only the connectors the run planned (enabled for the project, chosen and runnable at the start). A retried job
        # still sees its sources as partial: the final coverage of a group is written only when the group is done.
        self.planned = {c["connector_id"] for c in run["coverage"] if c["status"] == "partial"}
        gateway = gateway_for(db, self.settings, self.contracts)
        self._gateway = gateway if gateway.available else None
        # Per run, across every job and attempt: the identity agent's tasks already spent for this run are counted.
        used = db["ai_agent_runs"].count_documents({"run_id": self.run_id, "agent": "A01_project_identity"})
        self.a01_left = max(0, self.settings.identity_agent_tasks_per_run - used)
        self._progress_at: dict[str, float] = {}
        self._check = check
        self.check = self._checked
        self.started = time.monotonic()

    def _checked(self) -> str:
        """Between units of work: cancellation and a lost lease stop the job (the worker's check); a group that has
        worked longer than COLLECT_JOB_MAX_MINUTES stops where it is, with its coverage saying so."""
        beat = str(self._check())
        if time.monotonic() - self.started > self.settings.collect_job_max_minutes * 60:
            raise TimeLimitReached(f"stopped at the {self.settings.collect_job_max_minutes}-minute limit of a job")
        return beat

    @property
    def gateway(self) -> ModelGateway | None:
        """A01 for review segments, while this run's task budget lasts (cost bound)."""
        return self._gateway if self.a01_left > 0 else None

    def spent(self, report: dict[str, Any]) -> None:
        self.a01_left -= sum(1 for task in report.get("a01", []) if task.get("outcome") != "skipped")

    def progress(
        self, cov: dict[str, Any], doing: str, counts: dict[str, int] | None = None, *, now: bool = False
    ) -> None:
        """The source's counts so far, written while it works so the console shows them live (status partial, the
        note says what it is doing). At most once every PROGRESS_SECONDS per source unless `now`."""
        at = time.monotonic()
        if not now and at - self._progress_at.get(cov["connector_id"], 0.0) < PROGRESS_SECONDS:
            return
        self._progress_at[cov["connector_id"]] = at
        detail = _note(counts or {}, [])
        note = f"{IN_PROGRESS}{doing}" + (f"; {detail}" if detail else "")
        update_coverage(self.db, self.run_id, {**cov, "status": "partial", "note": note[:500]})

    def _build(self, connector_id: str) -> Any:
        return build(connector_id, self.db, self.settings) if connector_id in self.planned else None

    def _state(self, connector_id: str, query_text: str) -> tuple[dict[str, Any], str | None]:
        st = state.get(self.db, connector_id, self.project_id, query_text)
        saved = json.loads(st["cursor"]) if st["cursor"] else None
        cursor = saved["cursor"] if saved and saved.get("run") == self.run_id else None
        return st, cursor

    def _store_page(
        self, connector_id: str, st: dict[str, Any], page: Page, items: list[tuple[Item, dict[str, Any]]], done: bool
    ) -> list[Stored]:
        """Store a page's items, then advance its cursor, in one transaction."""
        cursor = None if done else json.dumps({"run": self.run_id, "cursor": page.next_cursor})

        def write(session: ClientSession) -> list[Stored]:
            stored = []
            for item, policy in items:
                if item.parent and "native_id" in item.parent:  # a reply: its top comment was stored just before
                    top = self.db["ai_sources"].find_one(
                        {"connector_id": item.connector_id, "native_id": item.parent["native_id"]},
                        sort=[("revision", -1)],
                        session=session,
                    )
                    item.parent = {"id": top["id"], "revision": top["revision"]} if top else None
                stored.append(store_item(self.db, item, policy, session))
            state.save(
                self.db, st, cursor=cursor, coverage="complete_for_query" if done else "partial", session=session
            )
            return stored

        return run_in_transaction(self.client, write)

    def _store_one(self, item: Item, policy: dict[str, Any]) -> Stored:
        def write(session: ClientSession) -> Stored:
            return store_item(self.db, item, policy, session)

        return run_in_transaction(self.client, write)

    def _queries(self, connector_id: str) -> list[dict[str, Any]]:
        reviews_only = self.settings.analysis_mode == "reviews"
        plan = build_query_plan(self.db, self.project_id, _registry(self.settings), reviews_only)["plan"]["queries"]
        return [q for q in plan if q["connector_id"] == connector_id]

    def _read_pages(
        self,
        web: WebFetch,
        urls: list[tuple[str, bool]],
        cov: dict[str, Any],
        outcomes: dict[str, int],
        limit: int,
    ) -> None:
        """Read each distinct page once, within `limit` real fetches (pages already read or withdrawn do not use it);
        store, identify and count it in `cov` and `outcomes`. Only a hit that names the project may use the paid
        fallbacks. A host that timed out twice is not asked again in this job; a page that fails in an unexpected way
        is counted, never the end of the job (audit, 14 Oct 2026)."""
        seen: set[str] = set()
        fetched = 0
        timeouts: dict[str, int] = {}
        for url, named in urls:
            if url in seen:
                continue
            seen.add(url)
            if fetched >= limit:
                _count(outcomes, "over_page_budget")
                continue
            if timeouts.get(urlsplit(url).hostname or "", 0) >= HOST_TIMEOUTS:
                _count(outcomes, "skipped:host_timed_out")
                continue
            self.check()
            if self._known(url, outcomes):
                continue
            fetched += 1
            more = self._fetch_and_read(web, url, named, cov, outcomes, timeouts)
            self.progress(cov, f"{fetched} of up to {limit} pages read", outcomes)
            if more and more not in seen and fetched < limit and not self._known(more, outcomes):
                seen.add(more)  # a portal's full review list, read once (D68)
                fetched += 1
                self._fetch_and_read(web, more, named, cov, outcomes, timeouts)

    def _known(self, url: str, outcomes: dict[str, int]) -> bool:
        """A page already stored (where it landed after redirects) or withdrawn on request is not read again."""
        landed = self.db["ai_fetch_log"].find_one(
            {"url": url, "outcome": "fetched", "final_url": {"$type": "string"}}, sort=[("at", -1)]
        )
        known = [url, landed["final_url"]] if landed else [url]
        existing = self.db["ai_sources"].find_one(
            {"connector_id": "web_fetch", "native_id": {"$in": known}, "lifecycle": "active"}, {"_id": 1}
        )
        if existing is not None:
            _count(outcomes, "already_read")
            return True
        withdrawn = self.db["ai_sources"].distinct(
            "id", {"connector_id": "web_fetch", "native_id": {"$in": known}, "lifecycle": "withdrawn"}
        )
        if any(withdrawn_on_request(self.db, source_id) for source_id in withdrawn):
            _count(outcomes, "withdrawn_on_request")
            return True
        return False

    def _fetch_and_read(
        self,
        web: WebFetch,
        url: str,
        named: bool,
        cov: dict[str, Any],
        outcomes: dict[str, int],
        timeouts: dict[str, int],
    ) -> str | None:
        try:
            outcome = web.fetch(url, run_id=self.run_id, paid=named)
        except (JobCancelled, JobLost, TimeLimitReached):
            raise
        except Exception as exc:
            log_event(logger, "page failed", level=logging.WARNING, url=url, error=type(exc).__name__)
            _count(outcomes, "error:internal")
            return None
        cov["attempted_queries"] += 1
        _count(outcomes, "error_will_retry" if outcome.status == "error" and outcome.retryable else outcome.status)
        if outcome.status == "error" and "timed out" in (outcome.reason or ""):
            host = urlsplit(url).hostname or ""
            timeouts[host] = timeouts.get(host, 0) + 1
        try:
            return self._read_one(outcome, cov, outcomes)
        except (JobCancelled, JobLost, TimeLimitReached):
            raise
        except Exception as exc:
            log_event(logger, "page not read", level=logging.WARNING, url=url, error=type(exc).__name__)
            _count(outcomes, "error:internal")
            return None

    def _read_one(self, outcome: FetchOutcome, cov: dict[str, Any], outcomes: dict[str, int]) -> str | None:
        """Store and identify one fetched page; split a portal or forum page into its reviews, but only a page that
        is about a project of the catalogue (any match not rejected): another project's reviews are never stored.
        Returns the URL of the portal's full review list when the page shows only part of it."""
        if outcome.item is None or outcome.policy is None:
            return None
        page_source = self._store_one(outcome.item, outcome.policy)
        if page_source.source["lifecycle"] == "withdrawn":
            return None
        cov["fetched"] += 1
        report = identify_source(
            self.client,
            self.db,
            self.contracts,
            page_source.source,
            focus_project_ids=[self.project_id],
            gateway=self.gateway,
            run_id=self.run_id,
        )
        self.spent(report)
        mine = [r for r in report["links"] if r["status"] != "rejected" and r["project_id"] == self.project_id]
        if mine:
            cov["matched"] += 1
        if outcome.policy["family"] not in policies.REVIEW_PAGE_FAMILIES or not outcome.html:
            return None
        if not any(r["status"] != "rejected" for r in report["links"]):
            _count(outcomes, "reviews_not_split:page_about_no_catalogue_project")
            return None
        found = page_reviews(page_source.source["canonical_url"], outcome.html, self._project_names())
        for reason, count in found.dropped.items():
            outcomes[f"reviews_left_out:{reason}"] = outcomes.get(f"reviews_left_out:{reason}", 0) + count
        page_link = None
        if mine:
            page_link = self.db["ai_project_source_links"].find_one({"_id": mine[0]["link_id"]})
        for review in found.reviews:
            self.check()
            stored = self._store_one(review_item(page_source.source, review), outcome.policy)
            if stored.source["lifecycle"] == "withdrawn":
                continue
            outcomes["reviews_stored"] = outcomes.get("reviews_stored", 0) + (1 if stored.created else 0)
            linked = identify_in_context(
                self.client, self.db, self.contracts, stored.source, page_link, self.gateway, run_id=self.run_id
            )
            self.spent(linked)
        return found.more_url

    def _search_names(self) -> list[str]:
        """Names that identify the project on their own (D17): its name and standalone aliases. A context-required
        name ("Parq") searched alone on Reddit brings unrelated threads, each read and matched (A01 can be paid)."""
        project = self.db["projects"].find_one({"_id": self.project_id}, {"project_name": 1}) or {}
        config = self.db["ai_project_configs"].find_one({"_id": self.project_id}, {"aliases": 1}) or {}
        standalone = [a["text"] for a in config.get("aliases", []) if a.get("mode") == "standalone"]
        names: list[str] = []
        for name in dict.fromkeys([project.get("project_name") or "", *standalone]):
            words = f" {normalise_text(name)} "
            # "DLF Privana West" repeats "DLF Privana": a search for the shorter name already finds it
            if name and not any(f" {normalise_text(kept)} " in words for kept in names):
                names.append(name)
        return names

    def _name_keys(self) -> list[list[str]]:
        """For the relevance test of search hits: each name's own words without the developer's ("DLF Privana" ->
        "privana", "Conscient Parq" -> "parq"), so "Privana by DLF" and "DLF's Privana" count too."""
        project = self.db["projects"].find_one({"_id": self.project_id}, {"developer": 1}) or {}
        developer = set(normalise_text(project.get("developer") or "").split())
        keys = []
        for name in self._search_names():
            words = normalise_text(name).split()
            own = [w for w in words if w not in developer] or words
            if own not in keys:
                keys.append(own)
        return keys

    def _project_names(self) -> list[str]:
        project = self.db["projects"].find_one({"_id": self.project_id}) or {}
        config = self.db["ai_project_configs"].find_one({"_id": self.project_id}, {"aliases": 1}) or {}
        names = [project.get("project_name") or "", *(project.get("alternate_names") or [])]
        return [n for n in dict.fromkeys(names + [a["text"] for a in config.get("aliases", [])]) if n]

    # --- web group: Brave discovery, then the web reader ---

    def run_web(self) -> None:
        brave = self._build("brave_search")
        web = self._build("web_fetch")
        brave_cov = _coverage("brave_search", "complete_for_query", None)
        web_cov = _coverage("web_fetch", "complete_for_query", None)
        skipped: dict[str, int] = {}
        outcomes: dict[str, int] = {}
        to_read: list[tuple[str, bool]] = []
        errors: list[str] = []
        # A portal or Quora hit is read only when its title or address names the project, and only a hit that names
        # the project may use Scrapfly or Firecrawl: the first live run read 80 MagicBricks pages of other DLF
        # projects for "DLF Privana" (14 Oct 2026).
        keys = self._name_keys()
        if brave is not None:
            queries = self._queries("brave_search")
            if web is not None:
                self.progress(web_cov, "waiting for the search results", now=True)
            for number, query in enumerate(queries, 1):
                self.check()
                self.progress(brave_cov, f"search {number} of {len(queries)}", skipped, now=number == 1)
                done_before = self.db[SEARCHES].find_one({"_id": f"{self.run_id}|{query['query_text']}"})
                if done_before is not None:  # a retried job: this search was finished and paid for already
                    to_read += [(url, named) for url, named in done_before["to_read"]]
                    for key, count in done_before["skipped"].items():
                        skipped[key] = skipped.get(key, 0) + count
                    brave_cov["attempted_queries"] += done_before["attempted"]
                    brave_cov["fetched"] += done_before["stored"]
                    brave_cov["metadata_only"] += done_before["stored"]
                    continue
                found: list[tuple[str, bool]] = []
                found_skipped: dict[str, int] = {}
                attempted = stored_count = 0
                st, cursor = self._state("brave_search", query["query_text"])
                finished = False
                while True:
                    try:
                        page = brave.discover(query, cursor)
                    except ProviderError as exc:
                        errors.append(exc.code)
                        state.save(
                            self.db,
                            st,
                            cursor=st["cursor"],
                            coverage="partial",
                            error={"code": exc.code, "message": exc.message, "retryable": exc.retryable},
                        )
                        brave_cov["status"] = "unavailable" if exc.code == "access_refused" else "partial"
                        break
                    attempted += page.attempted
                    keep: list[tuple[Item, dict[str, Any]]] = []
                    for item in page.items:
                        resolution = policies.resolve(self.db, item.canonical_url)
                        if resolution.family in ("youtube", "instagram_public", "reddit"):
                            name = resolution.family.split("_")[0]
                            _count(found_skipped, f"{name}_left_to_{name}_connector")
                            continue
                        if not resolution.may_collect or resolution.policy is None:
                            _count(found_skipped, f"not_collected:{resolution.family or 'unknown'}")
                            continue
                        keep.append((item, resolution.policy))
                        if resolution.family not in policies.WEB_FETCH_FAMILIES:
                            continue
                        named = names_the_project(item, keys)
                        if resolution.family in policies.REVIEW_PAGE_FAMILIES and not named:
                            _count(found_skipped, "not_read:no_project_name_in_title_or_address")
                            continue
                        found.append((item.canonical_url, named))
                    done = page.next_cursor is None
                    stored = self._store_page("brave_search", st, page, keep, done)
                    stored_count += len(stored)
                    st = state.get(self.db, "brave_search", self.project_id, query["query_text"])
                    if done:
                        finished = True
                        break
                    cursor = page.next_cursor
                to_read += found
                for key, count in found_skipped.items():
                    skipped[key] = skipped.get(key, 0) + count
                brave_cov["attempted_queries"] += attempted
                brave_cov["fetched"] += stored_count
                brave_cov["metadata_only"] += stored_count
                if finished:
                    self.db[SEARCHES].update_one(
                        {"_id": f"{self.run_id}|{query['query_text']}"},
                        {
                            "$setOnInsert": {
                                "run_id": self.run_id,
                                "to_read": [[url, named] for url, named in found],
                                "skipped": found_skipped,
                                "attempted": attempted,
                                "stored": stored_count,
                                "at": utcnow(),
                            }
                        },
                        upsert=True,
                    )
            brave_cov["last_success_at"] = utcnow() if brave_cov["attempted_queries"] else None
            # the searches are done; the coverage stays partial until the pages are read, so a retried job reads them
            self.progress(brave_cov, "searches done; reading the pages found", skipped, now=True)
        brave_cov["note"] = _note(skipped, errors)
        if web is not None:
            assert isinstance(web, WebFetch)
            # the paid fallbacks' allowances are per run: what earlier attempts of this run used is counted
            web.unblock_left = max(
                0, self.settings.unblocked_pages_per_run - self._fetch_log_count("^(fetched_unblocked|unblock_)")
            )
            web.render_left = max(
                0, self.settings.rendered_pages_per_run - self._fetch_log_count("^(fetched_rendered|render_)")
            )
            if brave is not None and not brave_cov["attempted_queries"] and errors:
                web_cov.update(
                    status="unavailable", note=f"not run: every search failed ({', '.join(sorted(set(errors)))})"
                )
            else:
                self._read_pages(web, to_read, web_cov, outcomes, self.settings.web_pages_per_run)
                web_cov["last_success_at"] = utcnow() if web_cov["fetched"] else None
                web_cov["note"] = _note(outcomes, [])
                if (
                    outcomes.get("error_will_retry")
                    or outcomes.get("over_page_budget")
                    or outcomes.get("error:internal")
                ):
                    web_cov["status"] = "partial"  # pages that may be read next time, or were left unread
        if brave is not None:
            update_coverage(self.db, self.run_id, brave_cov)
        if web is not None and brave is not None:
            update_coverage(self.db, self.run_id, web_cov)

    def _fetch_log_count(self, outcomes: str) -> int:
        return self.db["ai_fetch_log"].count_documents({"run_id": self.run_id, "outcome": {"$regex": outcomes}})

    # --- YouTube group: search and metadata, then comments on accepted videos ---

    def run_youtube(self) -> None:
        yt = self._build("youtube_data_api")
        cov = _coverage("youtube_data_api", "complete_for_query", None)
        counts: dict[str, int] = {}
        errors: list[str] = []
        if yt is None:
            return
        policy = policies.current(self.db, "youtube")
        if policy is None or not policy["collection_allowed"]:
            cov.update(status="unavailable", note="the youtube policy does not allow collection")
            update_coverage(self.db, self.run_id, cov)
            return
        videos: list[dict[str, Any]] = []
        searches = self._queries("youtube_data_api")[: self.settings.youtube_searches_per_project]
        for number, query in enumerate(searches, 1):
            self.check()
            self.progress(cov, f"search {number} of {len(searches)}", counts, now=number == 1)
            st, cursor = self._state("youtube_data_api", query["query_text"])
            try:
                page = yt.discover(query, cursor)
            except ProviderError as exc:
                errors.append(exc.code)
                state.save(
                    self.db,
                    st,
                    cursor=st["cursor"],
                    coverage="partial",
                    error={"code": exc.code, "message": exc.message, "retryable": exc.retryable},
                )
                cov["status"] = "partial"
                if exc.code in ("quota_exhausted", "quota_exceeded", "access_refused"):
                    break
                continue
            cov["attempted_queries"] += 1
            stored = self._store_page("youtube_data_api", st, page, [(i, policy) for i in page.items], True)
            for s in stored:
                if s.source["lifecycle"] == "withdrawn":  # withdrawn on request: never collected again
                    counts["withdrawn_on_request"] = counts.get("withdrawn_on_request", 0) + 1
                    continue
                cov["fetched"] += 1
                cov["metadata_only"] += 1
                links = identify_metadata(
                    self.client,
                    self.db,
                    s.source,
                    page.match_text.get(s.source["native_id"], s.source["title"] or ""),
                    focus_project_ids=[self.project_id],
                )
                mine = [lk for lk in links if lk["project_id"] == self.project_id]
                if any(lk["status"] != "rejected" for lk in mine):
                    cov["matched"] += 1
                active = next((lk for lk in mine if lk["status"] in ACTIVE_STATUSES), None)
                if active is not None:
                    videos.append({"source": s.source, "link": active})
                elif mine and mine[0]["status"] == "needs_review":
                    counts["videos_waiting_for_review"] = counts.get("videos_waiting_for_review", 0) + 1
        videos = list({v["source"]["id"]: v for v in videos}.values())  # a video found by two searches, once
        for number, video in enumerate(videos, 1):
            self.check()
            self.progress(cov, f"comments of video {number} of {len(videos)}", counts)
            self._comments(yt, video, policy, cov, counts, errors)
        cov["last_success_at"] = utcnow() if cov["attempted_queries"] else None
        cov["note"] = _note(counts, errors)
        update_coverage(self.db, self.run_id, cov)

    def _comments(
        self,
        yt: Any,
        video: dict[str, Any],
        policy: dict[str, Any],
        cov: dict[str, Any],
        counts: dict[str, int],
        errors: list[str],
    ) -> None:
        st, cursor = self._state("youtube_data_api", f"comments:{video['source']['native_id']}")
        top_links: dict[str, dict[str, Any]] = {}
        for _ in range(self.settings.youtube_comment_pages_per_video):
            try:
                page = yt.fetch_thread(video["source"], cursor)
            except ProviderError as exc:
                if exc.code == "comments_disabled":
                    counts["comments_disabled"] = counts.get("comments_disabled", 0) + 1
                    state.save(self.db, st, cursor=None, coverage="complete_for_query")
                else:
                    errors.append(exc.code)
                    cov["status"] = "partial"
                return
            items: list[tuple[Item, dict[str, Any]]] = [(item, policy) for item in page.items]
            done = page.next_cursor is None
            stored = self._store_page("youtube_data_api", st, page, items, done)
            for s in stored:
                cov["fetched"] += 1 if s.created else 0
                if not s.created:
                    continue
                parent = s.source.get("parent") or {}
                context = (
                    video["link"] if parent.get("id") == video["source"]["id"] else top_links.get(parent.get("id", ""))
                )
                report = identify_in_context(self.client, self.db, self.contracts, s.source, context, self.gateway)
                self.spent(report)
                mine = [r for r in report["links"] if r["project_id"] == self.project_id and r["status"] != "rejected"]
                if mine:
                    cov["matched"] += 1
                    link = self.db["ai_project_source_links"].find_one({"_id": mine[0]["link_id"]})
                    if link is not None:
                        top_links[s.source["id"]] = link
            st = state.get(self.db, "youtube_data_api", self.project_id, f"comments:{video['source']['native_id']}")
            if done:
                return
            cursor = page.next_cursor

    # --- registry group: the HRERA record of each of the project's RERA registrations ---

    def run_registry(self) -> None:
        from app.connectors.harera import HareraRegistry
        from app.connectors.registries import reader_for
        from app.sources.http import FetchError

        registry = self._build("harera_registry")
        if registry is None:
            return
        assert isinstance(registry, HareraRegistry)
        cov = _coverage("harera_registry", "complete_for_query", None)
        project = self.db["projects"].find_one({"_id": self.project_id}) or {}
        connector, reason = reader_for(project)
        if connector == "state_registry":  # another state's portal, by registration number (D57)
            self._run_state_registry(project, cov)
            return
        if connector != "harera_registry":  # a state without a reader: reported, never looked up elsewhere
            cov.update(status="access_pending", note=reason)
            update_coverage(self.db, self.run_id, cov)
            return
        rera_ids = [r["id_normalised"] for r in project.get("rera_registrations", [])]
        policy = policies.current(self.db, "official_records")
        if policy is None or not policy["collection_allowed"]:
            cov.update(status="unavailable", note="the official_records policy does not allow collection")
            update_coverage(self.db, self.run_id, cov)
            return
        try:
            self.check()
            listing = registry.listing(run_id=self.run_id)
        except FetchError as exc:
            cov.update(status="partial" if exc.retryable else "unavailable", note=f"{exc.code}: {exc.message}"[:500])
            update_coverage(self.db, self.run_id, cov)
            return
        counts: dict[str, int] = {}
        missing = [rid for rid in rera_ids if rid not in listing]
        for rera_id in rera_ids:
            if rera_id not in listing:
                continue
            self.check()
            cov["attempted_queries"] += 1
            stored = self._store_one(registry.item_for(listing[rera_id]), policy)
            counts["changed" if stored.changed else ("new" if stored.created else "unchanged")] = (
                counts.get("changed" if stored.changed else ("new" if stored.created else "unchanged"), 0) + 1
            )
            cov["fetched"] += 1
            report = identify_source(
                self.client, self.db, self.contracts, stored.source, focus_project_ids=[self.project_id]
            )
            if any(r["status"] != "rejected" and r["project_id"] == self.project_id for r in report["links"]):
                cov["matched"] += 1
        if missing:
            counts["not_on_the_registry_list"] = len(missing)
        cov["last_success_at"] = utcnow()
        note = _note(counts, []) or ""
        cov["note"] = (note + (f"; not listed: {', '.join(missing)}" if missing else ""))[:500] or None
        update_coverage(self.db, self.run_id, cov)

    def _run_state_registry(self, project: dict[str, Any], cov: dict[str, Any]) -> None:
        from app.connectors.registries import state_of
        from app.connectors.state_registry import PORTALS, StateRegistry

        state = state_of(project) or ""
        reader = build("state_registry", self.db, self.settings)
        assert isinstance(reader, StateRegistry)
        policy = policies.current(self.db, "official_records")
        if policy is None or not policy["collection_allowed"]:
            cov.update(status="unavailable", note="the official_records policy does not allow collection")
            update_coverage(self.db, self.run_id, cov)
            return
        numbers = [r["id_normalised"] for r in project.get("rera_registrations", [])]
        missing: list[str] = []
        for index, number in enumerate(numbers, 1):
            self.check()
            self.progress(cov, f"registration {index} of {len(numbers)}", now=index == 1)
            cov["attempted_queries"] += 1
            try:
                item = reader.record(state, number, run_id=self.run_id)
            except ProviderError as exc:
                missing.append(f"{number} ({exc.code})")
                continue
            if item is None:
                missing.append(number)
                continue
            stored = self._store_one(item, policy)
            cov["fetched"] += 1
            report = identify_source(
                self.client, self.db, self.contracts, stored.source, focus_project_ids=[self.project_id]
            )
            if any(r["status"] != "rejected" and r["project_id"] == self.project_id for r in report["links"]):
                cov["matched"] += 1
        found = cov["fetched"]
        note = f"{PORTALS[state].name}: {found} of {len(numbers)} registration records found"
        if not numbers:
            note = f"{PORTALS[state].name}: the project has no RERA number in its input; nothing to look up"
        cov["note"] = (note + (f"; not found: {', '.join(missing)}" if missing else ""))[:500]
        cov["status"] = "complete_for_query" if not missing else "partial"
        cov["last_success_at"] = utcnow() if found else None
        update_coverage(self.db, self.run_id, cov)

    # --- Instagram group: Brave finds public posts, Scrapfly reads them (D54) ---

    def run_instagram(self) -> None:
        from app.connectors.base import QuotaExhausted
        from app.connectors.instagram import InstagramPublic
        from app.sources.http import FetchError

        ig = self._build("instagram_public")
        if ig is None:
            return
        assert isinstance(ig, InstagramPublic)
        cov = _coverage("instagram_public", "complete_for_query", None)
        policy = policies.current(self.db, "instagram_public")
        if policy is None or not policy["collection_allowed"]:
            cov.update(status="unavailable", note="the instagram_public policy does not allow collection")
            update_coverage(self.db, self.run_id, cov)
            return
        counts: dict[str, int] = {}
        errors: list[str] = []
        posts: list[str] = []
        # The project's name and approved standalone aliases, quoted: unquoted plan texts brought back unrelated
        # profiles for every project in the 13 Oct 2026 run.
        plan = self._queries("instagram_public")
        base = plan[0] if plan else {"window_days": 90, "exclusions": [], "language": "en"}
        project = self.db["projects"].find_one({"_id": self.project_id}, {"project_name": 1}) or {}
        config = self.db["ai_project_configs"].find_one({"_id": self.project_id}, {"aliases": 1}) or {}
        names = [project.get("project_name", "")] + [
            a["text"] for a in config.get("aliases", []) if a.get("mode") == "standalone"
        ]
        queries = [{**base, "query_text": f'"{n}"'} for n in dict.fromkeys(n for n in names if n)]
        for number, query in enumerate(queries[: self.settings.instagram_queries_per_project], 1):
            self.check()
            self.progress(cov, f"search {number}", counts, now=number == 1)
            try:
                page = ig.discover(query, None)
            except ProviderError as exc:
                errors.append(exc.code)
                cov["status"] = "partial"
                break
            cov["attempted_queries"] += 1
            for key, count in page.skipped.items():
                counts[key] = counts.get(key, 0) + count
            posts += [item.canonical_url for item in page.items if item.canonical_url not in posts]
        # posts this run already paid Scrapfly for, in an earlier attempt of this job, count against the cap
        read = self.db["ai_fetch_log"].count_documents(
            {"run_id": self.run_id, "connector_id": "instagram_public", "outcome": {"$nin": ["not_allowed"]}}
        )
        for url in posts:
            if read >= self.settings.instagram_posts_per_project:
                counts["over_the_per_run_cap"] = counts.get("over_the_per_run_cap", 0) + 1
                continue
            self.check()
            shortcode = url.rstrip("/").rsplit("/", 1)[-1]
            known = self.db["ai_sources"].find_one(
                {"connector_id": "instagram_public", "native_id": shortcode},
                {"lifecycle": 1, "id": 1},
                sort=[("revision", -1)],
            )
            if known is not None:
                outcome = "withdrawn_on_request" if withdrawn_on_request(self.db, known["id"]) else "already_read"
                counts[outcome] = counts.get(outcome, 0) + 1
                continue
            read += 1
            self.progress(
                cov, f"post {read} of up to {min(len(posts), self.settings.instagram_posts_per_project)}", counts
            )
            try:
                item = ig.fetch_item(url, run_id=self.run_id)
            except QuotaExhausted:
                errors.append("credits_exhausted")
                cov["status"] = "partial"
                break
            except ProviderError as exc:
                errors.append(exc.code)
                cov["status"] = "unavailable" if exc.code == "access_refused" else "partial"
                break
            except FetchError as exc:
                counts[exc.code] = counts.get(exc.code, 0) + 1
                continue
            stored = self._store_one(item, policy)
            cov["fetched"] += 1
            report = identify_source(
                self.client,
                self.db,
                self.contracts,
                stored.source,
                focus_project_ids=[self.project_id],
                gateway=self.gateway,
            )
            self.spent(report)
            if any(r["status"] != "rejected" and r["project_id"] == self.project_id for r in report["links"]):
                cov["matched"] += 1
        cov["last_success_at"] = utcnow() if cov["fetched"] else None
        cov["note"] = _note(counts, errors)
        update_coverage(self.db, self.run_id, cov)

    # --- Reddit group: public threads naming the project, through PullPush (D67, D68) ---

    def run_reddit(self) -> None:
        reddit = self._build("reddit_public")
        if reddit is None:
            return
        cov = _coverage("reddit_public", "complete_for_query", None)
        counts: dict[str, int] = {}
        errors: list[str] = []
        policy = policies.current(self.db, "reddit")
        if policy is None or not policy["collection_allowed"]:
            cov.update(status="unavailable", note="the reddit policy does not allow collection")
            update_coverage(self.db, self.run_id, cov)
            return
        s = self.settings
        after = _reddit_after(self.db, self.run_id)
        threads: dict[str, dict[str, Any]] = {}
        loose: dict[str, dict[str, Any]] = {}
        names = self._search_names()[: s.reddit_names_per_project]
        for number, name in enumerate(names, 1):
            self.check()
            self.progress(cov, f"searching name {number} of {len(names)}", counts, now=number == 1)
            try:
                for post in reddit.posts_naming(name, after, s.reddit_posts_per_name):
                    threads.setdefault(post["id"], post)
                for comment in reddit.comments_naming(name, after, s.reddit_comment_hits_per_name):
                    loose.setdefault(comment["id"], comment)
            except ProviderError as exc:
                errors.append(exc.code)
                cov["status"] = "partial"
                continue
            cov["attempted_queries"] += 2
        missing: set[str] = set()
        for comment in loose.values():  # a comment naming the project in a thread whose post does not
            post_id = str(comment.get("link_id") or "").removeprefix("t3_")
            if not post_id or post_id in threads or post_id in missing or len(threads) >= s.reddit_threads_per_run:
                continue
            self.check()
            try:
                post = reddit.post(post_id)
            except ProviderError as exc:
                errors.append(exc.code)
                cov["status"] = "partial"
                missing.add(post_id)
                continue
            if post is None:
                missing.add(post_id)
            else:
                threads[post_id] = post
        chosen = list(threads.values())[: s.reddit_threads_per_run]
        for number, post in enumerate(chosen, 1):
            self.check()
            self.progress(cov, f"thread {number} of {len(chosen)}", counts)
            try:
                thread = reddit.thread(post, s.reddit_comments_per_thread)
            except ProviderError as exc:
                errors.append(exc.code)
                cov["status"] = "partial"
                continue
            if thread.via != "pullpush":
                counts[f"threads_read_via_{thread.via}"] = counts.get(f"threads_read_via_{thread.via}", 0) + 1
            self._store_thread(
                reddit_post_item(thread.post), [reddit_comment_item(c) for c in thread.comments], policy, cov, counts
            )
        cov["last_success_at"] = utcnow() if cov["fetched"] else None
        cov["note"] = _note(counts, errors)
        update_coverage(self.db, self.run_id, cov)

    def _store_thread(
        self,
        post: Item,
        comments: list[Item],
        policy: dict[str, Any],
        cov: dict[str, Any],
        counts: dict[str, int],
    ) -> None:
        """A post, then its comments under it: the post is matched on its own words; a comment that names no project
        inherits the post's accepted match (as YouTube comments inherit their video's)."""
        stored = self._store_one(post, policy)
        if stored.source["lifecycle"] == "withdrawn":
            counts["withdrawn_on_request"] = counts.get("withdrawn_on_request", 0) + 1
            return
        cov["fetched"] += 1
        report = identify_source(
            self.client,
            self.db,
            self.contracts,
            stored.source,
            focus_project_ids=[self.project_id],
            gateway=self.gateway,
        )
        self.spent(report)
        mine = [r for r in report["links"] if r["status"] != "rejected" and r["project_id"] == self.project_id]
        post_link = self.db["ai_project_source_links"].find_one({"_id": mine[0]["link_id"]}) if mine else None
        if mine:
            cov["matched"] += 1
        for item in comments:
            self.check()
            item.parent = {"id": stored.source["id"], "revision": stored.source["revision"]}
            child = self._store_one(item, policy)
            if child.source["lifecycle"] == "withdrawn":
                continue
            cov["fetched"] += 1 if child.created else 0
            linked = identify_in_context(self.client, self.db, self.contracts, child.source, post_link, self.gateway)
            self.spent(linked)
            if any(r["project_id"] == self.project_id and r["status"] != "rejected" for r in linked["links"]):
                cov["matched"] += 1


def names_the_project(item: Item, keys: list[list[str]]) -> bool:
    """Whether a search hit's title or address carries the project's own name words (Collector._name_keys): all words
    of one key, as words or run together ("dlfprivana"). Portal and Quora addresses are made from the page title
    (magicbricks.com/dlf-privana-south-sector-77-gurgaon-pdpid-...). A title in Devanagari cannot be judged this way
    and is read."""
    title = item.title or ""
    if any("\u0900" <= ch <= "\u097f" for ch in title):
        return True
    text = f"{title} {re.sub(r'[^0-9A-Za-z]+', ' ', item.canonical_url)}"
    words = set(normalise_text(text).split())
    compact = re.sub(r"[^0-9a-z]+", "", text.lower())
    return any(key and (all(w in words for w in key) or "".join(key) in compact) for key in keys)


def _reddit_after(db: Database[dict[str, Any]], run_id: str) -> Any:
    run = db[RUNS].find_one({"_id": run_id}, {"window": 1}) or {}
    return (run.get("window") or {}).get("from") or utcnow() - timedelta(days=365)


def _count(counts: dict[str, int], key: str, by: int = 1) -> None:
    counts[key] = counts.get(key, 0) + by


class TimeLimitReached(Exception):
    """A collect job worked longer than COLLECT_JOB_MAX_MINUTES: it stops where it is, keeping what it stored."""


def finalise_open_coverage(
    db: Database[dict[str, Any]],
    run_id: str,
    connectors: tuple[str, ...] | None,
    reason: str,
    *,
    final: bool = True,
) -> None:
    """Coverage still saying "queued" or "in progress" when its job can no longer finish it (the job failed, ran out
    of time, or the run was cancelled) says so: a source that started keeps its counts so far as partial, one that
    never started is unavailable (audit, 14 Oct 2026)."""
    run = db[RUNS].find_one({"_id": run_id}, {"coverage": 1}) or {"coverage": []}
    for c in run["coverage"]:
        note = c.get("note") or ""
        if connectors is not None and c["connector_id"] not in connectors:
            continue
        if c["status"] != "partial" or not (note == QUEUED or note.startswith(IN_PROGRESS)):
            continue
        started = note.startswith(IN_PROGRESS)
        detail = note[len(IN_PROGRESS) :] if started else ""
        entry = {
            **c,
            # a job that will be tried again keeps every source partial (planned): only a final end marks a source
            # that never started as unavailable
            "status": "partial" if started or not final else "unavailable",
            "note": (f"stopped: {reason}" + (f"; {detail}" if detail else ""))[:500],
        }
        update_coverage(db, run_id, entry)


def _note(counts: dict[str, int], errors: list[str]) -> str | None:
    parts = [f"{k}: {v}" for k, v in sorted(counts.items())]
    if errors:
        parts.append("errors: " + ", ".join(sorted(set(errors))))
    return "; ".join(parts)[:500] or None


def handle_collect(db: Database[dict[str, Any]], job: dict[str, Any], check: Any) -> str | None:
    """Worker handler for `collect` jobs."""
    group = job["logical_key"].rsplit(":", 1)[-1]
    run = db[RUNS].find_one({"_id": job["run_id"]})
    if run is None or run["stage"] != "collecting":
        return None
    runners = {
        "web": "run_web",
        "youtube_data_api": "run_youtube",
        "registry": "run_registry",
        "instagram": "run_instagram",
        "reddit": "run_reddit",
    }
    if group not in runners:
        raise ValueError(f"unknown collect group {group}")
    collector = Collector(db.client, db, job, check)
    log_event(logger, "collect started", run_id=job["run_id"], group=group)
    try:
        getattr(collector, runners[group])()
    except TimeLimitReached as exc:
        finalise_open_coverage(db, job["run_id"], GROUPS.get(group), str(exc))
    except (JobCancelled, JobLost):
        raise
    except Exception as exc:
        # a later attempt overwrites this; after the last one it stays, saying why the source is unfinished
        finalise_open_coverage(db, job["run_id"], GROUPS.get(group), f"error {type(exc).__name__}", final=False)
        raise
    finish_if_done(db.client, db, job["run_id"], exclude_job=job["_id"])
    return None
