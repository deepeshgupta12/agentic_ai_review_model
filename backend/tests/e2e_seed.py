"""Seed the browser-journey database (Step 09.7): fictional projects, a run analysed by the scripted model up to
findings review (pending findings and first-person reviews), and console users. Labelled fixture data only.

    MONGODB_DB=sy_poc_e2e E2E_PASSWORD=... uv run python -m tests.e2e_seed

Settings come from the real environment (the repository .env, as for the stack); only the database is mapped to the
journey database by the environment variable. It refuses any database whose name does not end in `_e2e` (fixture data
never enters sy_poc), drops and rebuilds that database, and makes no provider call: the analysis runs against the
scripted fake client of the workflow tests, whatever keys the environment holds.
"""

from __future__ import annotations

import json
import os
import sys
from datetime import UTC, datetime
from typing import Any

from pymongo import MongoClient

from app.config import REPO_ROOT, Settings
from app.contracts import ContractStore
from app.seed.projects import import_projects
from app.seed.users import seed_users
from app.setup.database import setup_database
from app.sources.policies import seed_policies

ROLES = {
    "e2e-moderator@example.test": ["moderator", "publisher", "researcher", "admin"],
    "e2e-analyst@example.test": ["analyst"],
}


def main() -> int:
    settings = Settings()
    name = settings.mongodb_db
    if not name.endswith("_e2e"):
        print(f"refusing to seed {name!r}: the journey database name must end in _e2e", file=sys.stderr)
        return 2
    password = os.environ.get("E2E_PASSWORD") or ""
    if len(password) < 12:
        print("E2E_PASSWORD (12 or more characters) is required", file=sys.stderr)
        return 2
    client: MongoClient[dict[str, Any]] = MongoClient(settings.mongodb_uri, tz_aware=True)
    client.drop_database(name)
    db = client[name]
    contracts = ContractStore(REPO_ROOT / "contracts" / "v1")
    setup_database(db, contracts)
    seed_policies(client, db, contracts, REPO_ROOT / "seed" / "source_policies.json")
    catalogue = json.loads((REPO_ROOT / "evals" / "identity" / "v1" / "catalogue.json").read_text("utf-8"))
    rows = import_projects(client, db, contracts, catalogue, settings.seed_dir)
    fictional = {r["project_name"]: r["project_id"] for r in rows}
    for email, roles in ROLES.items():
        seed_users(db, [{"email": email, "display_name": email.split("@")[0], "roles": roles}], password)

    # The analysis, with the workflow tests' scripted model in place of Claude (no network call).
    from app.workers import worker
    from app.workflows import analysis

    from .test_workflow import ScriptedModel, analysing_run

    model = ScriptedModel()

    def gateway(database: Any, s: Settings, c: ContractStore) -> Any:
        from app.agents.gateway import ModelGateway
        from app.agents.spend import SpendLedger

        return ModelGateway(s, c, client=model, sleep=lambda _s: None, ledger=SpendLedger(database, s))

    from app.sources import collection

    # The real environment holds real keys: in this process no connector is built (each is recorded as not run) and
    # the analysis uses the scripted client, so seeding never reaches a provider.
    collection.build = lambda *_args, **_kwargs: None  # type: ignore[assignment]
    # The full analysis, so the console journeys have findings to decide as well as reviews (the default is reviews
    # only, D68); the content journey selects reviews only.
    settings.analysis_mode = "full"
    analysis.get_settings = lambda: settings  # type: ignore[assignment]
    collection.get_settings = lambda: settings  # type: ignore[assignment]
    analysis.gateway_for = gateway  # type: ignore[assignment]
    analysis.default_embedder = lambda _s: None  # type: ignore[assignment]
    project, run = analysing_run(db, settings, contracts, fictional)
    # one source with a known date, so the page built from its review carries a dated credit line: the database
    # validator refused such pages until 16 Oct 2026 (D76) and the journeys never met one
    db["ai_sources"].update_one(
        {"source_kind": "forum_post", "connector_id": "web_fetch"},  # the post is long enough for the page
        {
            "$set": {
                "publication_date": {
                    "status": "known",
                    "value": datetime(2026, 8, 24, 7, 25, 36, tzinfo=UTC),
                    "precision": "instant",
                    "basis": "platform_metadata",
                }
            }
        },
    )
    while worker.run_one(db, "e2e-seed", 60) is not None:
        pass
    stage = db["ai_runs"].find_one({"_id": run["_id"]})["stage"]
    slug = db["projects"].find_one({"_id": project})["slug"]
    print(
        json.dumps(
            {"database": name, "project_id": project, "slug": slug, "run_stage": stage, "model_calls": model.calls}
        )
    )
    return 0 if stage == "findings_review" else 1


if __name__ == "__main__":
    raise SystemExit(main())
