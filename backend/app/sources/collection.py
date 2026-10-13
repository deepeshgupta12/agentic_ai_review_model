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
from datetime import timedelta
from typing import Any

from pymongo import MongoClient
from pymongo.client_session import ClientSession
from pymongo.database import Database
from ulid import ULID

from app import audit
from app.agents.gateway import ModelGateway, gateway_for
from app.config import Settings, get_settings
from app.connectors.base import Page, ProviderError
from app.connectors.registry import build
from app.connectors.web import WebFetch
from app.contracts import ContractStore, get_contracts, to_view
from app.db import run_in_transaction, utcnow
from app.errors import ApiError
from app.identity.links import ACTIVE_STATUSES
from app.identity.queries import build_query_plan
from app.identity.service import identify_in_context, identify_metadata, identify_source
from app.ids import new_id
from app.jobs import queue
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
    "alerts": ("google_alerts",),  # Step 08 (D56): Google Alerts by RSS, the free listening source
}
TERMINAL_JOB = {"completed", "failed", "cancelled"}


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
    window_days = body["window_days"] or config["refresh"]["lookback_days"]
    if "brave_search" in chosen and "web_fetch" not in chosen and "web_fetch" in enabled:
        chosen = [*chosen, "web_fetch"]  # discovery hits are read by the web reader
    coverage, groups = [], []
    runnable = {c for c in chosen if build(c, db, settings) is not None}
    for connector_id in chosen:
        if connector_id not in runnable:
            coverage.append(_coverage(connector_id, "access_pending", "no credential or adapter configured; not run"))
        elif connector_id == "web_fetch" and "brave_search" not in runnable:
            coverage.append(_coverage(connector_id, "access_pending", "not run: no discovery source (brave_search)"))
        else:
            coverage.append(_coverage(connector_id, "partial", "collecting"))
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
    for job in db["ai_jobs"].find({"run_id": run_id, "status": {"$nin": sorted(TERMINAL_JOB)}}):
        queue.cancel(db, job["_id"])
    db[RUNS].update_one(
        {"_id": run_id, "stage": run["stage"]},
        {"$set": {"stage": "cancelled", "updated_at": utcnow(), "outcome_note": f"Cancelled: {reason}"}},
    )
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
        # Only the connectors the run planned (enabled for the project, chosen and runnable at the start).
        self.planned = {c["connector_id"] for c in run["coverage"] if c["status"] == "partial"}
        gateway = gateway_for(db, self.settings, self.contracts)
        self._gateway = gateway if gateway.available else None
        self.a01_left = self.settings.identity_agent_tasks_per_run

    @property
    def gateway(self) -> ModelGateway | None:
        """A01 for review segments, while this run's task budget lasts (cost bound)."""
        return self._gateway if self.a01_left > 0 else None

    def spent(self, report: dict[str, Any]) -> None:
        self.a01_left -= sum(1 for task in report.get("a01", []) if task.get("outcome") != "skipped")

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
        plan = build_query_plan(self.db, self.project_id, _registry(self.settings))["plan"]["queries"]
        return [q for q in plan if q["connector_id"] == connector_id]

    def _read_pages(
        self, web: WebFetch, urls: list[str], cov: dict[str, Any], outcomes: dict[str, int], limit: int
    ) -> None:
        """Read each distinct page once, within `limit`; store, identify and count it in `cov` and `outcomes`."""
        seen: set[str] = set()
        for url in urls:
            if url in seen or len(seen) >= limit:
                continue
            seen.add(url)
            self.check()
            landed = self.db["ai_fetch_log"].find_one(
                {"url": url, "outcome": "fetched", "final_url": {"$type": "string"}}, sort=[("at", -1)]
            )
            known = [url, landed["final_url"]] if landed else [url]  # a redirect is stored where it landed
            existing = self.db["ai_sources"].find_one(
                {"connector_id": "web_fetch", "native_id": {"$in": known}, "lifecycle": "active"}, {"_id": 1}
            )
            if existing is not None:
                outcomes["already_read"] = outcomes.get("already_read", 0) + 1
                continue
            withdrawn = self.db["ai_sources"].distinct(
                "id", {"connector_id": "web_fetch", "native_id": {"$in": known}, "lifecycle": "withdrawn"}
            )
            if any(withdrawn_on_request(self.db, source_id) for source_id in withdrawn):
                outcomes["withdrawn_on_request"] = outcomes.get("withdrawn_on_request", 0) + 1
                continue  # not even requested again
            outcome = web.fetch(url, run_id=self.run_id)
            cov["attempted_queries"] += 1
            key = "error_will_retry" if outcome.status == "error" and outcome.retryable else outcome.status
            outcomes[key] = outcomes.get(key, 0) + 1
            if outcome.item is None or outcome.policy is None:
                continue
            page_source = self._store_one(outcome.item, outcome.policy)
            if page_source.source["lifecycle"] == "withdrawn":
                continue
            cov["fetched"] += 1
            report = identify_source(
                self.client,
                self.db,
                self.contracts,
                page_source.source,
                focus_project_ids=[self.project_id],
                gateway=self.gateway,
            )
            self.spent(report)
            if any(r["status"] != "rejected" and r["project_id"] == self.project_id for r in report["links"]):
                cov["matched"] += 1

    # --- web group: Brave discovery, then the web reader ---

    def run_web(self) -> None:
        brave = self._build("brave_search")
        web = self._build("web_fetch")
        brave_cov = _coverage("brave_search", "complete_for_query", None)
        web_cov = _coverage("web_fetch", "complete_for_query", None)
        skipped: dict[str, int] = {}
        outcomes: dict[str, int] = {}
        to_read: list[str] = []
        errors: list[str] = []
        if brave is not None:
            for query in self._queries("brave_search"):
                self.check()
                st, cursor = self._state("brave_search", query["query_text"])
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
                    brave_cov["attempted_queries"] += page.attempted
                    keep: list[tuple[Item, dict[str, Any]]] = []
                    for item in page.items:
                        resolution = policies.resolve(self.db, item.canonical_url)
                        if resolution.family in ("youtube", "instagram_public"):
                            name = resolution.family.split("_")[0]
                            key = f"{name}_left_to_{name}_connector"
                            skipped[key] = skipped.get(key, 0) + 1
                            continue
                        if not resolution.may_collect or resolution.policy is None:
                            key = f"not_collected:{resolution.family or 'unknown'}"
                            skipped[key] = skipped.get(key, 0) + 1
                            continue
                        keep.append((item, resolution.policy))
                        if resolution.family in policies.WEB_FETCH_FAMILIES:
                            to_read.append(item.canonical_url)
                    done = page.next_cursor is None
                    stored = self._store_page("brave_search", st, page, keep, done)
                    brave_cov["fetched"] += len(stored)
                    brave_cov["metadata_only"] += len(stored)
                    st = state.get(self.db, "brave_search", self.project_id, query["query_text"])
                    if done:
                        break
                    cursor = page.next_cursor
            brave_cov["last_success_at"] = utcnow() if brave_cov["attempted_queries"] else None
        brave_cov["note"] = _note(skipped, errors)
        # The web reader: each distinct URL once per run, within the page budget.
        if web is not None:
            assert isinstance(web, WebFetch)
            self._read_pages(web, to_read, web_cov, outcomes, self.settings.web_pages_per_run)
            web_cov["last_success_at"] = utcnow() if web_cov["fetched"] else None
            web_cov["note"] = _note(outcomes, [])
            if outcomes.get("error_will_retry"):  # a page that may read next time; permanent outcomes are decided
                web_cov["status"] = "partial"
        if brave is not None:
            update_coverage(self.db, self.run_id, brave_cov)
        if web is not None and brave is not None:
            update_coverage(self.db, self.run_id, web_cov)

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
        for query in self._queries("youtube_data_api")[: self.settings.youtube_searches_per_project]:
            self.check()
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
        for video in videos:
            self.check()
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
        from app.sources.http import FetchError

        registry = self._build("harera_registry")
        if registry is None:
            return
        assert isinstance(registry, HareraRegistry)
        cov = _coverage("harera_registry", "complete_for_query", None)
        project = self.db["projects"].find_one({"_id": self.project_id}) or {}
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

    # --- alerts group: Google Alerts feeds name new mentions; allow-listed pages are read (D56) ---

    def run_alerts(self) -> None:
        from app.connectors.alerts import GoogleAlerts
        from app.identity.text import normalise_text

        alerts = self._build("google_alerts")
        if alerts is None:
            return
        assert isinstance(alerts, GoogleAlerts)
        cov = _coverage("google_alerts", "complete_for_query", None)
        project = self.db["projects"].find_one({"_id": self.project_id}) or {}
        config = self.db["ai_project_configs"].find_one({"_id": self.project_id}) or {}
        names = [normalise_text(project.get("project_name", ""))] + [
            normalise_text(a["text"]) for a in config.get("aliases", []) if a.get("mode") == "standalone"
        ]
        counts: dict[str, int] = {}
        try:
            self.check()
            items, seen = alerts.mentions([n for n in names if n], run_id=self.run_id)
        except ProviderError as exc:
            cov.update(status="partial" if exc.retryable else "unavailable", note=f"{exc.code}: {exc.message}"[:500])
            update_coverage(self.db, self.run_id, cov)
            return
        counts.update(seen)
        cov["attempted_queries"] = seen.get("feeds_read", 0)
        to_read: list[str] = []
        for item in items:
            resolution = policies.resolve(self.db, item.canonical_url)
            if resolution.family in ("youtube", "instagram_public"):
                key = f"{resolution.family.split('_')[0]}_left_to_its_connector"
                counts[key] = counts.get(key, 0) + 1
                continue
            if not resolution.may_collect or resolution.policy is None:
                key = f"not_collected:{resolution.family or 'unknown'}"
                counts[key] = counts.get(key, 0) + 1
                continue
            self._store_one(item, resolution.policy)
            cov["metadata_only"] += 1
            if resolution.family in policies.WEB_FETCH_FAMILIES:
                to_read.append(item.canonical_url)
        # The web reader's own group may have finished already, so ask whether it was planned at all.
        run = self.db[RUNS].find_one({"_id": self.run_id}, {"coverage": 1}) or {"coverage": []}
        planned = any(c["connector_id"] == "web_fetch" and c["status"] != "access_pending" for c in run["coverage"])
        web = build("web_fetch", self.db, self.settings) if planned else None
        if web is not None and to_read:
            assert isinstance(web, WebFetch)
            self._read_pages(web, to_read, cov, counts, self.settings.alert_pages_per_run)
        cov["last_success_at"] = utcnow()
        cov["note"] = _note(counts, [])
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
        for query in queries[: self.settings.instagram_queries_per_project]:
            self.check()
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
        read = 0
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
    collector = Collector(db.client, db, job, check)
    log_event(logger, "collect started", run_id=job["run_id"], group=group)
    if group == "web":
        collector.run_web()
    elif group == "youtube_data_api":
        collector.run_youtube()
    elif group == "registry":
        collector.run_registry()
    elif group == "instagram":
        collector.run_instagram()
    elif group == "alerts":
        collector.run_alerts()
    else:
        raise ValueError(f"unknown collect group {group}")
    finish_if_done(db.client, db, job["run_id"], exclude_job=job["_id"])
    return None
