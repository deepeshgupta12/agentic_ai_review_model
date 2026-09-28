"""Command line for setup and checks:

python -m app.cli setup-db [--dry-run]
python -m app.cli seed-projects [--input PATH]
python -m app.cli seed-users [--reset-password]
python -m app.cli smoke-model
python -m app.cli check-config
"""

from __future__ import annotations

import argparse
import getpass
import json
import os
import sys
from pathlib import Path

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
    from app.seed.projects import SeedError, seed_projects

    db = get_db()
    try:
        report = seed_projects(db.client, db, get_contracts(), Path(args.input), get_settings().seed_dir)
    except SeedError as exc:
        print(f"seed-projects failed: {exc}", file=sys.stderr)
        return 1
    _print(report)
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
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    sys.exit(main())
