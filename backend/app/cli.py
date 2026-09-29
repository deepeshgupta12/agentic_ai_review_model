"""Command line for setup and checks:

python -m app.cli setup-db [--dry-run]
python -m app.cli seed-projects [--input PATH]
python -m app.cli seed-users [--reset-password]
python -m app.cli smoke-model
python -m app.cli check-config
python -m app.cli match-text --text TEXT [--focus SLUG ...]   (dry run: nothing is stored)
python -m app.cli plan-queries [--project SLUG]
python -m app.cli eval-identity [--save]
python -m app.cli fixture-smoke-identity [--live-a01]   (fictional catalogue in a scratch database, dropped)
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
    from app.agents.gateway import ModelGateway

    settings = get_settings()
    gateway = ModelGateway(settings, get_contracts())
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
        plan = build_query_plan(db, project_id, connectors)
        errors = get_contracts().errors(plan["plan"], "agents.schema.json#/$defs/DiscoveryPlan")
        if errors:
            print(
                f"plan-queries: plan for {project_id} breaks the DiscoveryPlan contract: {errors[:3]}", file=sys.stderr
            )
            return 1
        plans.append(plan)
    _print(plans)
    return 0


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
    from app.workers.worker import run_one

    settings, contracts = get_settings(), get_contracts()
    client = get_db().client
    scratch = client[f"sy_poc_smoke_{secrets.token_hex(4)}"]
    checks: dict[str, bool] = {}
    live: dict[str, Any] | str = "not requested"
    try:
        setup_database(scratch, contracts)
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
                seed_dir=settings.seed_dir,
            )

        comparison = source(
            "c1",
            "Two options.\n\nQuillon Residences in Sector 102: big balconies.\n\n"
            "Tavira Vista in Sector 88: good finish.",
        )
        report = identify_source(client, scratch, contracts, settings.seed_dir, comparison, focus_project_ids=[q])
        links = {row["project_id"]: row for row in report["links"]}
        checks["comparison: one source, two projects, distinct segments"] = (
            set(links) == {q, t}
            and scratch["ai_sources"].count_documents({}) == 1
            and links[q]["segment_key"] != links[t]["segment_key"]
        )
        elsewhere = source("c2", "Quillon Residences in Pune has a lovely clubhouse.")
        other = identify_source(client, scratch, contracts, settings.seed_dir, elsewhere, focus_project_ids=[q])
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
        decided = decide_link(client, scratch, contracts, settings.seed_dir, link["_id"], body, moderator)
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
    from app.agents.gateway import ModelGateway
    from app.identity.service import identify_source

    gateway = ModelGateway(settings, contracts)
    if not gateway.available:
        return "skipped: no ANTHROPIC_API_KEY configured"
    review = source(
        "live-a01",
        "Quillon Residences, Gurgaon: locals call the lake-facing towers QR Lakeside. "
        "Possession of the second phase keeps slipping.",
    )
    report = identify_source(
        client, scratch, contracts, settings.seed_dir, review, focus_project_ids=[project_id], gateway=gateway
    )
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
    p = sub.add_parser("eval-identity", help="identity evaluation on the labelled dataset")
    p.add_argument("--save", action="store_true", help="store the result in ai_evaluations")
    p.set_defaults(func=cmd_eval_identity)
    p = sub.add_parser("fixture-smoke-identity", help="identity path on the fictional catalogue in a scratch database")
    p.add_argument("--live-a01", action="store_true", help="also make one real A01 call (needs ANTHROPIC_API_KEY)")
    p.set_defaults(func=cmd_fixture_smoke_identity)
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    sys.exit(main())
