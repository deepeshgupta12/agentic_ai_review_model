"""Command line for setup and checks:

python -m app.cli setup-db [--dry-run]
python -m app.cli seed-policies
python -m app.cli sync-catalogue   (at every stack start: policies loaded, new registry sources added to projects)
python -m app.cli seed-projects [--input PATH]
python -m app.cli seed-users [--reset-password]
python -m app.cli smoke-model
python -m app.cli check-config
python -m app.cli match-text --text TEXT [--focus SLUG ...]   (dry run: nothing is stored)
python -m app.cli plan-queries [--project SLUG]
python -m app.cli eval-identity [--save]
python -m app.cli fixture-smoke-identity [--live-a01]   (fictional catalogue in a scratch database, dropped)
python -m app.cli discover-hosts [--project SLUG] [--queries N]   (live Brave; stores nothing)
python -m app.cli collect [--project SLUG] [--window-days N] [--wait SECONDS]   (a real collection run)
python -m app.cli recheck-sources [--project SLUG] [--wait SECONDS]   (edits, deletions and stated dates)
python -m app.cli verify-collection   (read-only checks over what collection stored)
python -m app.cli transcribe-videos [--project SLUG] [--limit N] [--wait SECONDS]   (media worker)
python -m app.cli eval-media [--model NAME] [--save]   (synthetic speech check; media worker image)
python -m app.cli eval-language [--save]   (A04 translation check; one Claude call)
"""

from __future__ import annotations

import argparse
import getpass
import json
import os
import sys
from pathlib import Path
from typing import Any

from app.config import REPO_ROOT, get_settings
from app.contracts import get_contracts
from app.db import get_db


def _print(data: object) -> None:
    print(json.dumps(data, indent=2, default=str))


def cmd_setup_db(args: argparse.Namespace) -> int:
    from app.setup.database import setup_database

    _print(setup_database(get_db(), get_contracts(), dry_run=args.dry_run))
    return 0


def cmd_seed_projects(args: argparse.Namespace) -> int:
    from app.seed.projects import SeedError, seed_projects, seed_status_records

    db = get_db()
    settings = get_settings()
    try:
        report = seed_projects(db.client, db, get_contracts(), Path(args.input), settings.seed_dir)
        statuses = seed_status_records(db.client, db, get_contracts(), settings.seed_dir / "construction_status.json")
    except SeedError as exc:
        print(f"seed-projects failed: {exc}", file=sys.stderr)
        return 1
    _print({"projects": report, "construction_status": statuses})
    return 0


def cmd_seed_policies(_: argparse.Namespace) -> int:
    from app.sources.policies import PolicyError, seed_policies

    db = get_db()
    try:
        report = seed_policies(db.client, db, get_contracts(), get_settings().seed_dir / "source_policies.json")
    except PolicyError as exc:
        print(f"seed-policies failed: {exc}", file=sys.stderr)
        return 1
    _print(report)
    return 0


def cmd_sync_catalogue(_: argparse.Namespace) -> int:
    """At every stack start (the db-setup service): the repository's source policies are loaded (immutable versions;
    nothing changes when they are current) and every project's sources follow the connector registry, so a source
    added later (such as Reddit, D67) reaches the projects that existed before it. A new project gets it at once."""
    from app.seed.projects import sync_registry_sources
    from app.sources.policies import PolicyError, seed_policies

    db, settings = get_db(), get_settings()
    try:
        policies = seed_policies(db.client, db, get_contracts(), settings.seed_dir / "source_policies.json")
    except PolicyError as exc:
        print(f"sync-catalogue failed: {exc}", file=sys.stderr)
        return 1
    changed = [p for p in policies if p.get("outcome") != "unchanged"]
    _print({"policies_changed": changed, "projects_synced": sync_registry_sources(db.client, db, settings.seed_dir)})
    return 0


def cmd_seed_users(args: argparse.Namespace) -> int:
    from app.auth.passwords import WeakPasswordError
    from app.seed.users import seed_users, seeded_users

    password = os.environ.get("SEED_USER_PASSWORD") or None
    if password is None and sys.stdin.isatty():
        password = getpass.getpass("Password for the seeded user (12+ characters, not shown): ") or None
    try:
        report = seed_users(
            get_db(), seeded_users(get_settings().seed_dir), password, reset_password=args.reset_password
        )
    except (WeakPasswordError, ValueError) as exc:
        print(f"seed-users failed: {exc}", file=sys.stderr)
        return 1
    _print(report)
    return 0


def cmd_smoke_model(_: argparse.Namespace) -> int:
    from app.agents.gateway import gateway_for

    settings = get_settings()
    gateway = gateway_for(get_db(), settings, get_contracts())
    if not gateway.available:
        print("skipped: no ANTHROPIC_API_KEY configured (connector anthropic stays access_pending)")
        return 0
    models = gateway.check_models()
    result = gateway.run(
        "routine",
        "agents.schema.json#/$defs/SynthesisResult",
        "You synthesise evidence-backed findings. Use only the evidence supplied. If there is none, abstain.",
        "Evidence supplied: none. Return your result.",
        max_tokens=1024,
    )
    _print(
        {
            "models": models,
            "outcome": result.outcome,
            "model_outcome": (result.data or {}).get("outcome"),
            "requested_model": result.requested_model,
            "returned_model": result.returned_model,
            "stop_reason": result.stop_reason,
            "provider_request_id": result.provider_request_id,
            "usage": result.usage,
            "error": result.error,
        }
    )
    all_available = all(entry["status"] == "available" for entry in models.values())
    return 0 if result.outcome == "completed" and all_available else 1


def cmd_check_config(_: argparse.Namespace) -> int:
    settings = get_settings()
    connectors = json.loads((settings.seed_dir / "connectors.json").read_text(encoding="utf-8"))
    names = sorted(
        {name for item in connectors["model_providers"] + connectors["connectors"] for name in item["credential_env"]}
    )
    _print(
        {
            "mode": settings.app_mode.value,
            "mongodb_db": settings.mongodb_db,
            "models": {
                "routine": settings.model_routine,
                "reasoning": settings.model_reasoning,
                "difficult": settings.model_difficult,
            },
            "credentials_present": {name: settings.credential_present(name) for name in names},
            "anthropic_workspace_id_set": settings.anthropic_workspace_id is not None,
        }
    )
    return 0


def _slug_to_id(db: Any, slug: str) -> str:
    project = db["projects"].find_one({"slug": slug}, {"_id": 1})
    if project is None:
        raise SystemExit(f"no project with slug {slug!r}; run seed-projects first")
    return str(project["_id"])


def cmd_match_text(args: argparse.Namespace) -> int:
    """Show what the deterministic matcher decides for a text, without storing anything."""
    from app.identity.catalogue import load_identities
    from app.identity.matching import match_text

    db = get_db()
    focus = [_slug_to_id(db, s) for s in args.focus]
    identities = load_identities(db)
    names = {i.id: i.slug for i in identities}
    outcomes = match_text(identities, args.text, focus)
    _print(
        [
            {
                "project": names[o.project_id],
                "segment": o.segment.key,
                "status": o.status,
                "rule_score": o.rule_score,
                "signals": o.signals,
                "matched_alias": o.matched_alias,
                "phase": o.phase,
                "rationale": o.rationale,
            }
            for o in outcomes
        ]
        or "no catalogue project is named in this text"
    )
    return 0


def cmd_plan_queries(args: argparse.Namespace) -> int:
    from app.identity.queries import build_query_plan

    db = get_db()
    settings = get_settings()
    registry = json.loads((settings.seed_dir / "connectors.json").read_text(encoding="utf-8"))
    connectors = {c["id"]: c for c in registry["connectors"]}
    ids = [_slug_to_id(db, args.project)] if args.project else [p["_id"] for p in db["projects"].find({}, {"_id": 1})]
    plans = []
    for project_id in ids:
        plan = build_query_plan(db, project_id, connectors, get_settings().analysis_mode == "reviews")
        errors = get_contracts().errors(plan["plan"], "agents.schema.json#/$defs/DiscoveryPlan")
        if errors:
            print(
                f"plan-queries: plan for {project_id} breaks the DiscoveryPlan contract: {errors[:3]}", file=sys.stderr
            )
            return 1
        plans.append(plan)
    _print(plans)
    return 0


def cmd_discover_hosts(args: argparse.Namespace) -> int:
    """Live Brave discovery for the allow-list decision: which hosts come up, and what their policies say.
    Nothing is stored except the quota reservation."""
    from collections import Counter

    from app.connectors.base import ProviderError
    from app.connectors.registry import build
    from app.identity.queries import build_query_plan
    from app.sources.policies import resolve

    db, settings = get_db(), get_settings()
    brave = build("brave_search", db, settings)
    if brave is None:
        print("skipped: no BRAVE_SEARCH_API_KEY configured")
        return 0
    registry = json.loads((settings.seed_dir / "connectors.json").read_text(encoding="utf-8"))
    connectors = {c["id"]: c for c in registry["connectors"]}
    ids = [_slug_to_id(db, args.project)] if args.project else [p["_id"] for p in db["projects"].find({}, {"_id": 1})]
    hosts: Counter[str] = Counter()
    examples: dict[str, str] = {}
    requests = 0
    for project_id in ids:
        queries = [
            q
            for q in build_query_plan(db, project_id, connectors, get_settings().analysis_mode == "reviews")["plan"][
                "queries"
            ]
            if q["connector_id"] == "brave_search"
        ]
        for query in queries[: args.queries]:
            try:
                page = brave.discover(query, None)
            except ProviderError as exc:
                print(f"brave: {exc.code}: {exc.message}", file=sys.stderr)
                return 1
            requests += 1
            for item in page.items:
                host = resolve(db, item.canonical_url).host
                hosts[host] += 1
                examples.setdefault(host, item.canonical_url)
    rows = []
    for host, count in hosts.most_common():
        r = resolve(db, examples[host])
        rows.append(
            {
                "host": host,
                "results": count,
                "family": r.family,
                "may_collect_now": r.may_collect,
                "reason": r.reason,
                "example": examples[host],
            }
        )
    _print({"requests": requests, "distinct_hosts": len(rows), "hosts": rows})
    return 0


def cmd_collect(args: argparse.Namespace) -> int:
    """Start a collection run per project as the seeded researcher (the audit event records `via: cli`), then wait
    for the worker service to finish collecting. The worker must be running."""
    import time

    from app.errors import ApiError
    from app.seed.users import seeded_users
    from app.sources.collection import start_run

    db, settings = get_db(), get_settings()
    email = args.as_user or next(
        (u["email"] for u in seeded_users(settings.seed_dir) if "researcher" in u["roles"]), ""
    )
    user = db["users"].find_one({"email": email.strip().lower(), "roles": "researcher", "active": True})
    if user is None:
        print(f"collect: no active researcher {email!r}; run seed-users first", file=sys.stderr)
        return 1
    actor = {"kind": "user", "user_id": user["_id"], "role": "researcher"}
    ids = [_slug_to_id(db, args.project)] if args.project else [p["_id"] for p in db["projects"].find({}, {"_id": 1})]
    started = []
    for project_id in ids:
        body = {"window_days": args.window_days, "connectors": None}
        try:
            started.append(start_run(db.client, db, settings, project_id, body, actor, via="cli")["run_id"])
        except ApiError as exc:
            print(f"collect: {project_id}: {exc.code}: {exc.message}", file=sys.stderr)
            return 1
    deadline = time.monotonic() + args.wait
    while time.monotonic() < deadline:
        if db["ai_runs"].count_documents({"_id": {"$in": started}, "stage": "collecting"}) == 0:
            break
        time.sleep(5)
    rows = []
    for run in db["ai_runs"].find({"_id": {"$in": started}}):
        project = db["projects"].find_one({"_id": run["project_id"]}, {"project_name": 1})
        errors = db["ai_run_events"].find({"run_id": run["_id"], "type": "error"}, {"message": 1}).limit(5)
        rows.append(
            {
                "run_id": run["_id"],
                "project": project["project_name"] if project else run["project_id"],
                "stage": run["stage"],
                "coverage": [{k: v for k, v in c.items() if k != "last_success_at"} for c in run["coverage"]],
                "errors": [e["message"] for e in errors],
            }
        )
    _print(rows)
    still = [r["run_id"] for r in rows if r["stage"] == "collecting"]
    if still:
        print(
            f"collect: still collecting after {args.wait}s (the worker keeps going): {', '.join(still)}",
            file=sys.stderr,
        )
    return 0


def cmd_transcribe_videos(args: argparse.Namespace) -> int:
    """Queue transcription for project-matched videos without a transcript; the media worker processes them."""
    import time

    from app.media.pipeline import start_media

    db, settings = get_db(), get_settings()
    project_id = _slug_to_id(db, args.project) if args.project else None
    report = start_media(db, project_id, args.limit if args.limit is not None else settings.media_videos_per_start)
    deadline = time.monotonic() + args.wait
    while time.monotonic() < deadline:
        if (
            db["ai_jobs"].count_documents(
                {"kind": "process_media", "status": {"$in": ["queued", "running", "retry_wait"]}}
            )
            == 0
        ):
            break
        time.sleep(10)
    statuses: dict[str, int] = {}
    for video in db["ai_sources"].find({"connector_id": "youtube_data_api", "source_kind": "video"}, {"media": 1}):
        key = f"{video['media']['access_status']} ({video['media'].get('transcript_route') or 'no route'})"
        statuses[key] = statuses.get(key, 0) + 1
    reasons: dict[str, int] = {}
    for event in db["ai_audit_events"].find(
        {"action": "media_access.changed", "details.to": {"$in": ["metadata_only", "error"]}}
    ):
        reason = str(event["details"].get("reason", "")).split(":")[0]
        reasons[reason] = reasons.get(reason, 0) + 1
    frames_skipped: dict[str, int] = {}
    for event in db["ai_audit_events"].find({"action": "media_frames.skipped"}):
        reason = str(event["details"].get("reason", "")).split(":")[0]
        frames_skipped[reason] = frames_skipped.get(reason, 0) + 1
    _print(
        {
            "queued": report,
            "videos_by_status": statuses,
            "refusal_or_error_reasons": reasons,
            "segments": db["ai_media_segments"].count_documents({}),
            "speech_evidence": db["ai_evidence"].count_documents({"modality": "speech"}),
            "frame_evidence": db["ai_evidence"].count_documents({"modality": {"$in": ["on_screen_text", "frame"]}}),
            "frames_skipped": frames_skipped,
        }
    )
    return 0


def cmd_eval_media(args: argparse.Namespace) -> int:
    """The synthetic speech check (evals/media/v1) with the configured Whisper model. Needs the media dependencies."""
    from app.db import utcnow
    from app.ids import new_id
    from app.media.evaluation import evaluate, evaluation_record
    from app.media.fetch import WhisperTranscriber

    settings = get_settings()
    model = args.model or settings.whisper_model
    result = evaluate(
        REPO_ROOT / "evals" / "media" / "v1",
        WhisperTranscriber(model, settings.whisper_compute_type, settings.whisper_models_dir, max_seconds=120),
        model,
    )
    record = evaluation_record(result)
    if args.save:
        record = {"_id": new_id("evl"), **record, "created_at": utcnow()}
        get_db()["ai_evaluations"].insert_one(record)
    _print(
        {
            **{k: v for k, v in result.items() if k != "rows"},
            "saved_as": record.get("_id"),
            "rows": [
                {k: r[k] for k in ("id", "language", "wer", "facts_kept", "facts", "real_time_factor", "transcript")}
                for r in result["rows"]
            ],
        }
    )
    return 0


def cmd_eval_language(args: argparse.Namespace) -> int:
    """A04 on the known text of the non-English speech cases (one Claude call); numbers and negation must survive."""
    from app.agents.gateway import gateway_for
    from app.db import utcnow
    from app.ids import new_id
    from app.media.evaluation import evaluate_translation

    settings, contracts = get_settings(), get_contracts()
    gateway = gateway_for(get_db(), settings, contracts)
    if not gateway.available:
        print("skipped: no ANTHROPIC_API_KEY configured")
        return 0
    result = evaluate_translation(REPO_ROOT / "evals" / "media" / "v1", gateway)
    rows = result["rows"]
    facts = sum(r["facts"] for r in rows)
    record: dict[str, Any] = {
        "dataset": result["dataset"],
        "config": {
            "agent": "A04_language_context",
            "model": result["model"],
            "prompt_version": "a04_language_context.1.0",
            "schema_version": "1.0.0",
        },
        "status": "completed" if result["outcome"] == "completed" else "failed",
        "metrics": [
            {
                "name": "translations_kept_by_backend",
                "value": round(sum(r["kept_by_backend"] for r in rows) / len(rows), 3) if rows else None,
                "sample_size": len(rows),
                "note": "numbers and negation in the original must survive the translation",
            },
            {
                "name": "english_facts_kept",
                "value": round(sum(r["facts_kept"] for r in rows) / facts, 3) if facts else None,
                "sample_size": facts,
                "note": "synthetic sentences written for this check; real transcripts are harder",
            },
        ],
    }
    if args.save:
        record = {"_id": new_id("evl"), **record, "created_at": utcnow()}
        get_db()["ai_evaluations"].insert_one(record)
    _print({**result, "saved_as": record.get("_id")})
    return 0 if result["outcome"] == "completed" else 1


def cmd_eval_frames(args: argparse.Namespace) -> int:
    """A03 on the synthetic frames (one Claude vision call): each frame's text read verbatim, no render called real
    footage."""
    from app.agents.gateway import gateway_for
    from app.db import utcnow
    from app.ids import new_id
    from app.media.evaluation import evaluate_frames, frames_record

    settings, contracts = get_settings(), get_contracts()
    gateway = gateway_for(get_db(), settings, contracts)
    if not gateway.available:
        print("skipped: no ANTHROPIC_API_KEY configured")
        return 0
    result = evaluate_frames(REPO_ROOT / "evals" / "media" / "v1", gateway)
    record = frames_record(result)
    if args.save:
        record = {"_id": new_id("evl"), **record, "created_at": utcnow()}
        get_db()["ai_evaluations"].insert_one(record)
    _print({**result, "saved_as": record.get("_id")})
    return 0 if result["outcome"] == "completed" else 1


def cmd_recheck_sources(args: argparse.Namespace) -> int:
    """Queue an availability re-check (edits, deletions, stated dates) and wait for the worker to finish it."""
    import time

    from app.sources.recheck import start_recheck

    db = get_db()
    project_id = _slug_to_id(db, args.project) if args.project else None
    job_id = start_recheck(db, project_id)["job_id"]
    deadline = time.monotonic() + args.wait
    job = db["ai_jobs"].find_one({"_id": job_id}) or {}
    while time.monotonic() < deadline and job.get("status") not in ("completed", "failed", "cancelled"):
        time.sleep(5)
        job = db["ai_jobs"].find_one({"_id": job_id}) or {}
    event = db["ai_audit_events"].find_one({"action": "sources.rechecked", "target.id": job_id})
    _print({"job_id": job_id, "status": job.get("status"), "result": event["details"] if event else None})
    return 0 if job.get("status") == "completed" else 1


def cmd_verify_collection(_: argparse.Namespace) -> int:
    """Read-only checks over what collection stored: policies, robots, metadata-only, threads, quotas, coverage."""
    from app.sources.verify import verify_collection

    rows = verify_collection(get_db(), get_settings())
    _print(rows)
    return 0 if all(r["ok"] for r in rows) else 1


def cmd_verify_evidence(_: argparse.Namespace) -> int:
    """Read-only checks over the evidence layer: anchors, links, erasure, search index, clusters, lineage."""
    from app.evidence.verify import verify_evidence

    rows = verify_evidence(get_db())
    _print(rows)
    return 0 if all(r["ok"] for r in rows) else 1


def cmd_verify_analysis(_: argparse.Namespace) -> int:
    """Read-only checks over claims, findings, reviews, approvals and model spend (Step 08)."""
    from app.workflows.verify import verify_analysis

    rows = verify_analysis(get_db(), get_contracts(), get_settings())
    _print(rows)
    return 0 if all(r["ok"] for r in rows) else 1


def cmd_sample_sheet(args: argparse.Namespace) -> int:
    """The sample sheet of real claims, findings and reviews for the product owner's review (D53), as CSV on standard
    output. It quotes third-party posts: save it under exports/ (git-ignored), never in the repository."""
    from app.workflows.sample import sample_csv

    sys.stdout.write(sample_csv(get_db(), args.claims, args.reviews))
    return 0


def cmd_cluster_origins(_: argparse.Namespace) -> int:
    """Group copies of one origin (exact and near-duplicate texts, copied passages) into origin clusters (D50)."""
    from app.evidence.clusters import cluster_origins

    db = get_db()
    _print(cluster_origins(db.client, db))
    return 0


def cmd_add_evidence_context(_: argparse.Namespace) -> int:
    """Give evidence stored before Step 07 its context window, once (audited)."""
    from app.evidence.anchors import backfill_context

    db = get_db()
    _print(backfill_context(db.client, db))
    return 0


def cmd_search_evidence(args: argparse.Namespace) -> int:
    """Keyword search over one project's eligible evidence, with filters (D50)."""
    from app.embeddings.client import default_embedder
    from app.evidence.retrieval import search

    db = get_db()
    result = search(
        db,
        _slug_to_id(db, args.project),
        args.query,
        modalities=args.modality or None,
        languages=args.language or None,
        limit=args.limit,
        embedder=default_embedder(get_settings()),
        mode=args.mode,
    )
    _print(
        {
            **{k: v for k, v in result.items() if k != "items"},
            "items": [
                {
                    "evidence": f"{i['evidence']['id']}@{i['evidence']['revision']}",
                    "score": i["score"],
                    "keyword_score": i["keyword_score"],
                    "similarity": i["similarity"],
                    "modality": i["evidence"]["modality"],
                    "language": i["evidence"]["language"],
                    "flags": i["flags"],
                    "excerpt": (i["evidence"]["excerpt_text"] or "")[:160],
                }
                for i in result["items"]
            ],
        }
    )
    return 0


def cmd_eval_retrieval(args: argparse.Namespace) -> int:
    """Retrieval benchmark on the labelled synthetic set (evals/retrieval/v1) in a scratch database, dropped after."""
    from app.db import utcnow
    from app.embeddings.client import default_embedder
    from app.evidence.benchmark import benchmark_record, run_benchmark
    from app.ids import new_id

    settings, contracts = get_settings(), get_contracts()
    db = get_db()
    result = run_benchmark(
        db.client,
        contracts,
        settings,
        REPO_ROOT / "evals" / "retrieval" / "v1",
        REPO_ROOT / "evals" / "identity" / "v1" / "catalogue.json",
        embedder=None if args.keyword_only else default_embedder(settings, for_job=True),
    )
    record = benchmark_record(result)
    if args.save:
        record = {"_id": new_id("evl"), **record, "created_at": utcnow()}
        db["ai_evaluations"].insert_one(record)
    _print({**result, "saved_as": record.get("_id")})
    clean = all(
        r["wrong_project_results"] == r["withdrawn_results"] == r["anchor_errors"] == 0
        for r in result["by_retriever"].values()
    )
    return 0 if clean and not result["unlinked_documents"] else 1


def cmd_eval_identity(args: argparse.Namespace) -> int:
    from app.db import utcnow
    from app.identity.evaluation import evaluate_dataset, load_dataset
    from app.ids import new_id

    contracts = get_contracts()
    catalogue, cases = load_dataset(REPO_ROOT / "evals" / "identity" / "v1", contracts)
    result = evaluate_dataset(catalogue, cases)
    record = {k: result[k] for k in ("dataset", "config", "status", "metrics")}
    if args.save:
        record = {"_id": new_id("evl"), **record, "created_at": utcnow()}
        get_db()["ai_evaluations"].insert_one(record)
    summary = {
        "dataset": result["dataset"],
        "rules": result["config"]["schema_version"],
        "metrics": {
            m["name"]: {"value": m["value"], "n": m["sample_size"], "note": m["note"]} for m in result["metrics"]
        },
        "auto_accept_precision_target_met": result["target_met"],
        "saved_as": record.get("_id"),
        "caution": "synthetic, fictional cases written with the rules; they show the rules behave as designed, "
        "not real-world precision (real labels at Step 12)",
    }
    _print(summary)
    return 0 if result["target_met"] else 1


def cmd_fixture_smoke_identity(args: argparse.Namespace) -> int:
    """The whole identity path on the fictional catalogue in a scratch database: source, match, links,
    evidence, a moderator correction and the worker's invalidation job. The real catalogue is untouched."""
    import secrets

    from app.identity.intake import store_text_source
    from app.identity.links import decide_link
    from app.identity.service import identify_source
    from app.ids import new_id
    from app.seed.projects import import_projects
    from app.setup.database import setup_database
    from app.sources.policies import seed_policies
    from app.workers.worker import run_one

    settings, contracts = get_settings(), get_contracts()
    client = get_db().client
    scratch = client[f"sy_poc_smoke_{secrets.token_hex(4)}"]
    checks: dict[str, bool] = {}
    live: dict[str, Any] | str = "not requested"
    try:
        setup_database(scratch, contracts)
        seed_policies(client, scratch, contracts, settings.seed_dir / "source_policies.json")
        data = json.loads((REPO_ROOT / "evals" / "identity" / "v1" / "catalogue.json").read_text(encoding="utf-8"))
        ids = {
            r["project_name"]: r["project_id"]
            for r in import_projects(client, scratch, contracts, data, settings.seed_dir)
        }
        q, t = ids["Quillon Residences"], ids["Tavira Vista"]

        def source(native_id: str, text: str) -> dict[str, Any]:
            return store_text_source(
                scratch,
                connector_id="firecrawl",
                native_id=native_id,
                canonical_url=f"https://smoke.example.test/{native_id}",
                source_kind="forum_post",
                text=text,
                policy_family="web_public_pages",
            )

        comparison = source(
            "c1",
            "Two options.\n\nQuillon Residences in Sector 102: big balconies.\n\n"
            "Tavira Vista in Sector 88: good finish.",
        )
        report = identify_source(client, scratch, contracts, comparison, focus_project_ids=[q])
        links = {row["project_id"]: row for row in report["links"]}
        checks["comparison: one source, two projects, distinct segments"] = (
            set(links) == {q, t}
            and scratch["ai_sources"].count_documents({}) == 1
            and links[q]["segment_key"] != links[t]["segment_key"]
        )
        elsewhere = source("c2", "Quillon Residences in Pune has a lovely clubhouse.")
        other = identify_source(client, scratch, contracts, elsewhere, focus_project_ids=[q])
        checks["same name in another city is rejected"] = [r["status"] for r in other["links"]] == ["rejected"]
        link = scratch["ai_project_source_links"].find_one({"_id": links[q]["link_id"]})
        if link is None:
            raise RuntimeError("the comparison produced no link for Quillon Residences")
        checks["evidence created for the accepted segment"] = (
            scratch["ai_evidence"].count_documents({"link_id": link["_id"]}) == 1
        )
        moderator = {"kind": "user", "user_id": new_id("usr"), "role": "moderator"}
        body = {
            "action": "reject",
            "expected_version": link["version"],
            "reason": "fixture smoke check",
            "split_segments": None,
            "remap_project_id": None,
            "phase_rera_id": None,
        }
        decided = decide_link(client, scratch, contracts, link["_id"], body, moderator)
        checks["moderator correction recorded"] = decided["status"] == "rejected" and decided["decided_by"] is not None
        status = run_one(scratch, "smoke-worker", 30)
        audit = scratch["ai_audit_events"].find_one({"action": "dependencies.invalidated"})
        checks["worker ran the invalidation job"] = status == "completed" and audit is not None
        checks["evidence on the rejected link is now ineligible"] = (
            audit is not None and audit["details"]["evidence_made_ineligible"] == 1
        )
        if args.live_a01:
            live = _live_a01_check(client, scratch, contracts, settings, source, q, checks)
    finally:
        client.drop_database(scratch.name)
    summary: dict[str, Any] = {"scratch_database": scratch.name, "dropped": True, "checks": checks}
    if args.live_a01:
        summary["live_a01"] = live
    _print(summary)
    return 0 if checks and all(checks.values()) else 1


def cmd_plan_analysis(args: argparse.Namespace) -> int:
    """Dry run before any spend (D53): per project, the A05 and A11 tasks the analysis would send and their worst-case
    cost from the price table. A06 and A07 depend on the claims A05 finds; the run budget bounds them. Stores
    nothing and calls no model; tasks whose output is already cached cost nothing and are counted apart."""
    from app.agents import claims as a05
    from app.agents import reviews as a11
    from app.agents.common import cached_output
    from app.agents.spend import estimate_input_tokens, worst_case_usd

    db, settings = get_db(), get_settings()
    ids = [_slug_to_id(db, args.project)] if args.project else [p["_id"] for p in db["projects"].find({}, {"_id": 1})]
    rows, total = [], 0.0
    for project_id in ids:
        project = db["projects"].find_one({"_id": project_id})
        assert project is not None
        row: dict[str, Any] = {"project": project["project_name"]}
        for name, module, tasks in (
            ("a05", a05, a05.build_tasks(db, project_id)),
            ("a11", a11, a11.build_tasks(db, project_id)),
        ):
            model = settings.model_for_role(module.ROLE)
            system = module.PROMPT_PATH.read_text("utf-8")
            fresh = [t for t in tasks if cached_output(db, t["key"]) is None]
            worst = sum(
                worst_case_usd(
                    settings,
                    model,
                    estimate_input_tokens(system, module.render(db, project, t)[0]),
                    module.MAX_OUTPUT_TOKENS,
                    batch=False,
                )
                for t in fresh
            )
            row[name] = {
                "model": model,
                "tasks": len(tasks),
                "cached": len(tasks) - len(fresh),
                "worst_usd": round(worst, 4),
            }
            total += worst
        rows.append(row)
    _print({"projects": rows, "worst_case_usd_a05_a11": round(total, 4), "budget_usd": settings.model_budget_usd})
    return 0


def cmd_analyse(args: argparse.Namespace) -> int:
    """Queue the analysis of a run again after a stop (budget, model access). The worker continues the run's graph
    from its last checkpoint and reuses cached outputs."""
    from app.workflows.analysis import analyse_again

    try:
        _print(analyse_again(get_db(), args.run))
    except ValueError as exc:
        print(f"analyse: {exc}", file=sys.stderr)
        return 1
    return 0


def cmd_analysis_report(args: argparse.Namespace) -> int:
    """A run's stage, spend and the analysis report kept in its graph state (counts only, no source words)."""
    from app.workflows.analysis import saver_for, spent_usd, thread_of

    db = get_db()
    run = db["ai_runs"].find_one({"_id": args.run})
    if run is None:
        print(f"analysis-report: no run {args.run}", file=sys.stderr)
        return 1
    saved = saver_for(db).get_tuple(thread_of(args.run))  # type: ignore[arg-type]
    values = saved.checkpoint["channel_values"] if saved else {}
    jobs = [
        {"kind": j["kind"], "status": j["status"], "error": j["error"]}
        for j in db["ai_jobs"].find({"run_id": args.run, "kind": {"$in": ["analyse", "resume_after_review"]}})
    ]
    _print(
        {
            "run_id": args.run,
            "stage": run["stage"],
            "outcome_note": run["outcome_note"],
            "spent_usd": round(spent_usd(db, args.run), 6),
            "claims": len(values.get("claims") or []),
            "findings": len(values.get("findings") or []),
            "reviews": len(values.get("reviews") or []),
            "report": values.get("report"),
            "jobs": jobs,
        }
    )
    return 0


def cmd_eval_agents(args: argparse.Namespace) -> int:
    """The agents on the labelled synthetic set (evals/agents/v1) in a scratch database, dropped after. Live calls
    count against the model budget (D53); `--light-model` compares routing for A05 and A11."""
    from app.agents.evaluation import evaluation_record, run_agent_eval
    from app.db import utcnow
    from app.ids import new_id

    settings, contracts, db = get_settings(), get_contracts(), get_db()
    if not settings.credential_present("ANTHROPIC_API_KEY"):
        print("eval-agents: skipped, no ANTHROPIC_API_KEY (access_pending)", file=sys.stderr)
        return 0
    result = run_agent_eval(
        db.client,
        contracts,
        settings,
        db,
        REPO_ROOT / "evals" / "agents" / "v1",
        REPO_ROOT / "evals" / "identity" / "v1" / "catalogue.json",
        light_model=args.light_model,
    )
    record = evaluation_record(result)
    if args.save:
        record = {"_id": new_id("evl"), **record, "created_at": utcnow()}
        db["ai_evaluations"].insert_one(record)
    _print({**result, "saved_as": record.get("_id")})
    return 0 if result["summary"]["forbidden_claims"] == 0 and not result["unlinked_documents"] else 1


def _live_a01_check(
    client: Any,
    scratch: Any,
    contracts: Any,
    settings: Any,
    source: Any,
    project_id: str,
    checks: dict[str, bool],
) -> dict[str, Any] | str:
    """One real A01 call on a fictional review segment (a few cents). Skipped without an API key."""
    from app.agents.gateway import gateway_for
    from app.identity.service import identify_source

    gateway = gateway_for(get_db(), settings, contracts)
    if not gateway.available:
        return "skipped: no ANTHROPIC_API_KEY configured"
    review = source(
        "live-a01",
        "Quillon Residences, Gurgaon: locals call the lake-facing towers QR Lakeside. "
        "Possession of the second phase keeps slipping.",
    )
    report = identify_source(client, scratch, contracts, review, focus_project_ids=[project_id], gateway=gateway)
    a01 = report["a01"][0] if report["a01"] else None
    link = scratch["ai_project_source_links"].find_one({"source.id": review["id"], "project_id": project_id})
    run = scratch["ai_agent_runs"].find_one({"agent": "A01_project_identity"})
    checks["live A01 answered in the contract shape"] = bool(a01) and a01 is not None and a01["error"] is None
    checks["live A01 cannot accept: the link stays in review"] = link is not None and link["status"] == "needs_review"
    checks["live A01 call recorded with the returned model and usage"] = bool(
        run and run["returned_model"] and run["usage"]["input_tokens"]
    )
    return {
        "requested_model": run["requested_model"] if run else None,
        "returned_model": run["returned_model"] if run else None,
        "provider_request_id": run["provider_request_id"] if run else None,
        "usage": run["usage"] if run else None,
        "outcome": a01["outcome"] if a01 else None,
        "error": a01["error"] if a01 else None,
        "link_rationale": link["match"]["rationale"][:400] if link else None,
        "alias_proposals": [
            {"alias": r["alias_text"], "outcome": r["outcome"], "reason": r["reason"]}
            for r in (a01["alias_proposals"] if a01 else [])
        ],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.cli")
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("setup-db", help="create collections, validators and indexes")
    p.add_argument("--dry-run", action="store_true")
    p.set_defaults(func=cmd_setup_db)
    p = sub.add_parser("seed-projects", help="load the five-project input file")
    p.add_argument("--input", default=str(REPO_ROOT / "contracts" / "five-project-input-template.json"))
    p.set_defaults(func=cmd_seed_projects)
    sub.add_parser(
        "sync-catalogue", help="load the source policies and give every project the registry's new sources"
    ).set_defaults(func=cmd_sync_catalogue)
    sub.add_parser("seed-policies", help="load seed/source_policies.json (immutable versions)").set_defaults(
        func=cmd_seed_policies
    )
    p = sub.add_parser("seed-users", help="create the seeded users (password from SEED_USER_PASSWORD or a prompt)")
    p.add_argument("--reset-password", action="store_true")
    p.set_defaults(func=cmd_seed_users)
    sub.add_parser("smoke-model", help="one real structured-output call, or 'skipped' without a key").set_defaults(
        func=cmd_smoke_model
    )
    sub.add_parser("check-config", help="show mode, models and which credentials are present").set_defaults(
        func=cmd_check_config
    )
    p = sub.add_parser("match-text", help="dry run of project matching on a text (stores nothing)")
    p.add_argument("--text", required=True)
    p.add_argument("--focus", nargs="*", default=[], help="slugs of projects whose search found the text")
    p.set_defaults(func=cmd_match_text)
    p = sub.add_parser("plan-queries", help="bounded search queries per project (approved aliases only)")
    p.add_argument("--project", help="project slug; all projects when omitted")
    p.set_defaults(func=cmd_plan_queries)
    p = sub.add_parser("discover-hosts", help="live Brave discovery: hosts found and their policy (stores nothing)")
    p.add_argument("--project", help="project slug; all projects when omitted")
    p.add_argument("--queries", type=int, default=2, help="queries per project (each is one Brave request)")
    p.set_defaults(func=cmd_discover_hosts)
    p = sub.add_parser("collect", help="start a real collection run per project and wait for the worker")
    p.add_argument("--project", help="project slug; all projects when omitted")
    p.add_argument("--window-days", type=int, default=None, help="look-back window; the project config when omitted")
    p.add_argument("--wait", type=int, default=900, help="seconds to wait for collection to finish (0: do not wait)")
    p.add_argument("--as", dest="as_user", help="researcher email; the seeded researcher when omitted")
    p.set_defaults(func=cmd_collect)
    p = sub.add_parser("transcribe-videos", help="queue transcription of project-matched videos (media worker)")
    p.add_argument("--project", help="project slug; all projects when omitted")
    p.add_argument("--limit", type=int, default=None, help="videos to queue; MEDIA_VIDEOS_PER_START when omitted")
    p.add_argument("--wait", type=int, default=0, help="seconds to wait for the media worker")
    p.set_defaults(func=cmd_transcribe_videos)
    p = sub.add_parser("eval-media", help="synthetic speech check with the Whisper model (media worker image)")
    p.add_argument("--model", help="Whisper model; WHISPER_MODEL when omitted")
    p.add_argument("--save", action="store_true", help="store the result in ai_evaluations")
    p.set_defaults(func=cmd_eval_media)
    p = sub.add_parser("eval-language", help="A04 translation check on the synthetic speech cases (one Claude call)")
    p.add_argument("--save", action="store_true", help="store the result in ai_evaluations")
    p.set_defaults(func=cmd_eval_language)
    p = sub.add_parser("eval-frames", help="A03 frame check on the synthetic frames (one Claude vision call)")
    p.add_argument("--save", action="store_true", help="store the result in ai_evaluations")
    p.set_defaults(func=cmd_eval_frames)
    p = sub.add_parser("recheck-sources", help="re-check stored sources for edits and deletions (worker job)")
    p.add_argument("--project", help="project slug; every re-checkable source when omitted")
    p.add_argument("--wait", type=int, default=1800, help="seconds to wait for the worker")
    p.set_defaults(func=cmd_recheck_sources)
    sub.add_parser("verify-collection", help="read-only checks over what collection stored").set_defaults(
        func=cmd_verify_collection
    )
    sub.add_parser("verify-evidence", help="read-only checks over evidence, the search index and lineage").set_defaults(
        func=cmd_verify_evidence
    )
    sub.add_parser("cluster-origins", help="group copies of one origin into origin clusters").set_defaults(
        func=cmd_cluster_origins
    )
    sub.add_parser("add-evidence-context", help="give older evidence its context window, once").set_defaults(
        func=cmd_add_evidence_context
    )
    p = sub.add_parser("eval-retrieval", help="retrieval benchmark on the labelled synthetic set (scratch database)")
    p.add_argument("--save", action="store_true", help="store the result in ai_evaluations")
    p.add_argument("--keyword-only", action="store_true", help="skip the embedder (keyword ranking only)")
    p.set_defaults(func=cmd_eval_retrieval)
    p = sub.add_parser("search-evidence", help="keyword search over a project's eligible evidence")
    p.add_argument("--project", required=True, help="project slug")
    p.add_argument("--query", default="", help="words to look for; empty lists the newest evidence")
    p.add_argument("--modality", action="append", help="text, speech, on_screen_text or frame (repeatable)")
    p.add_argument("--language", action="append", help="language tag, e.g. hi or en (repeatable)")
    p.add_argument("--limit", type=int, default=10)
    p.add_argument("--mode", choices=["hybrid", "keyword", "vector"], default="hybrid")
    p.set_defaults(func=cmd_search_evidence)
    p = sub.add_parser("eval-identity", help="identity evaluation on the labelled dataset")
    p.add_argument("--save", action="store_true", help="store the result in ai_evaluations")
    p.set_defaults(func=cmd_eval_identity)
    p = sub.add_parser("fixture-smoke-identity", help="identity path on the fictional catalogue in a scratch database")
    p.add_argument("--live-a01", action="store_true", help="also make one real A01 call (needs ANTHROPIC_API_KEY)")
    p.set_defaults(func=cmd_fixture_smoke_identity)
    p = sub.add_parser("eval-agents", help="agents on the labelled synthetic set (live calls, within the budget)")
    p.add_argument("--light-model", help="model for the light role (A05, A11) instead of the configured one")
    p.add_argument("--save", action="store_true", help="store the result in ai_evaluations")
    p.set_defaults(func=cmd_eval_agents)
    sub.add_parser("verify-analysis", help="read-only checks over claims, findings, reviews and spend").set_defaults(
        func=cmd_verify_analysis
    )
    p = sub.add_parser("sample-sheet", help="CSV sample of real claims, findings and reviews for review (D53)")
    p.add_argument("--claims", type=int, default=10, help="claims per project")
    p.add_argument("--reviews", type=int, default=4, help="reviews per project")
    p.set_defaults(func=cmd_sample_sheet)
    p = sub.add_parser("plan-analysis", help="dry run: the agent tasks an analysis would send and their worst case")
    p.add_argument("--project", help="project slug (default: all five)")
    p.set_defaults(func=cmd_plan_analysis)
    p = sub.add_parser("analyse", help="queue a run's analysis again after a stop (continues from its checkpoint)")
    p.add_argument("--run", required=True)
    p.set_defaults(func=cmd_analyse)
    p = sub.add_parser("analysis-report", help="a run's stage, spend and analysis report")
    p.add_argument("--run", required=True)
    p.set_defaults(func=cmd_analysis_report)
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    sys.exit(main())
