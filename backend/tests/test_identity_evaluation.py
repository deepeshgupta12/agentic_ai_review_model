"""UC-32: the identity evaluation (Step 04.8). It must report every metric with its sample size, label the
dataset as synthetic, and meet the 98% auto-accept precision target on this dataset."""

from __future__ import annotations

from app.config import REPO_ROOT
from app.identity.evaluation import TARGET_AUTO_PRECISION, evaluate_dataset, load_dataset

DATASET = REPO_ROOT / "evals" / "identity" / "v1"


def test_the_evaluation_reports_metrics_with_sample_sizes(contracts):
    catalogue, cases = load_dataset(DATASET, contracts)
    result = evaluate_dataset(catalogue, cases)
    record = {k: result[k] for k in ("dataset", "config", "status", "metrics")}
    record.update(id="evl_01K0000000000000000000000A", created_at="2026-09-28T00:00:00Z")
    assert contracts.errors(record, "operations.schema.json#/$defs/EvaluationRun") == []
    assert result["dataset"]["synthetic"] is True
    metrics = {m["name"]: m for m in result["metrics"]}
    assert all(m["sample_size"] > 0 for m in metrics.values())
    assert metrics["auto_accept_precision"]["value"] >= TARGET_AUTO_PRECISION and result["target_met"]
    assert metrics["not_relevant_kept_out_of_auto"]["value"] == 1.0
    assert metrics["same_name_other_city_rejected"]["value"] == 1.0


def test_the_dataset_only_uses_fictional_projects(contracts):
    catalogue, cases = load_dataset(DATASET, contracts)
    real = {"dlf", "privana", "conscient", "sobha", "crescent", "m3m", "forestia", "antalya"}
    text = " ".join([c["text"] for c in cases["cases"]] + [p["project_name"] for p in catalogue["projects"]]).casefold()
    assert not [w for w in real if w in text]
    assert all(r["id"].startswith("TST/") for p in catalogue["projects"] for r in p["rera_ids"])


def test_the_fixture_smoke_check_passes_and_leaves_nothing_behind(db, settings, contracts, monkeypatch, capsys):
    import json

    from app import cli

    monkeypatch.setattr(cli, "get_db", lambda: db)
    monkeypatch.setattr(cli, "get_settings", lambda: settings)
    monkeypatch.setattr(cli, "get_contracts", lambda: contracts)
    before = set(db.client.list_database_names())
    assert cli.main(["fixture-smoke-identity"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["dropped"] and len(report["checks"]) == 6 and all(report["checks"].values())
    assert set(db.client.list_database_names()) == before, "the scratch database is dropped"
    assert db["projects"].count_documents({}) == 0, "the database under test is untouched"
