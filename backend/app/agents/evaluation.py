"""Agent evaluation on the labelled synthetic set (Step 08.7; evals/agents/v1; D53).

A scratch database gets the fictional catalogue, the construction statuses and the labelled posts through the real
intake and identity path. The agents then run as the workflow runs them (A05 claims, A06 verification against the
registry record, claims stored, A07 findings, A11 reviews), with every backend check, and the outputs are scored
against labels written with the posts:
- A05: expected claims found (aspect and polarity, and type where labelled), forbidden claims produced (sarcasm read
  as praise, an injected "fact", a question turned into a claim, marketing presented as a buyer's view), claims
  beyond the labels (reported, not scored: a label set is never complete), and the D27 flag where labelled;
- A06: claims that must not be verified (possession dates from posts) and the registry fact that should be;
- A07: the expected finding kinds per aspect and attributions that must not appear;
- A11: whether a source should give a review, and its polarity.
`light_model` replaces the light role's model (A05, A11) for a routing comparison. Live calls go through the spend
ledger of the given database, so they count against the model budget (D53). The scratch database is dropped
afterwards. Small and synthetic: a routing check, not a measure of quality on real chatter.
"""

from __future__ import annotations

import json
import secrets
import time
from pathlib import Path
from typing import Any

from pymongo import MongoClient
from pymongo.database import Database

from app.agents import claims as a05
from app.agents import findings as a07
from app.agents import reviews as a11
from app.agents import verify as a06
from app.agents.gateway import ModelGateway
from app.agents.spend import SpendLedger
from app.config import Settings
from app.contracts import ContractStore
from app.evidence.clusters import cluster_origins
from app.identity.intake import store_text_source
from app.identity.service import identify_source
from app.seed.projects import import_projects
from app.setup.database import setup_database
from app.sources.policies import seed_policies
from app.workers.worker import run_one

RUN_ID = "run_01K0EVA1000000000000000000"  # fixed, so the scratch run is easy to recognise


def _rule_matches(claim: dict[str, Any], rule: dict[str, Any]) -> bool:
    if rule.get("any"):
        return True
    for key in ("aspect", "polarity", "claim_type", "perspective"):
        if key in rule and claim[key] not in rule[key]:
            return False
    if "statement_contains" in rule:
        statement = claim["statement"].lower()
        return any(part.lower() in statement for part in rule["statement_contains"])
    return True


def _store(scratch: Database[dict[str, Any]], doc: dict[str, Any]) -> dict[str, Any]:
    registry = doc["family"] == "official_records"
    host = "haryanarera.gov.in" if registry else "agents.example.test"
    return store_text_source(
        scratch,
        connector_id="harera_registry" if registry else "web_fetch",
        native_id=f"https://{host}/{doc['id']}",
        canonical_url=f"https://{host}/{doc['id']}",
        source_kind=doc["kind"],
        text=doc["text"],
        policy_family=doc["family"],
        language=doc.get("language"),
    )


def run_agent_eval(
    client: MongoClient[dict[str, Any]],
    contracts: ContractStore,
    settings: Settings,
    ledger_db: Database[dict[str, Any]] | None,
    directory: Path,
    catalogue: Path,
    *,
    light_model: str | None = None,
    gateway: ModelGateway | None = None,
) -> dict[str, Any]:
    data = json.loads((directory / "cases.json").read_text(encoding="utf-8"))
    run_settings = settings.model_copy(update={"model_light": light_model}) if light_model else settings
    if gateway is None:
        assert ledger_db is not None, "live calls need the spend ledger (D53)"
        gateway = ModelGateway(run_settings, contracts, ledger=SpendLedger(ledger_db, settings))
    scratch = client[f"sy_poc_agents_{secrets.token_hex(4)}"]
    started = time.monotonic()
    try:
        setup_database(scratch, contracts)
        seed_policies(client, scratch, contracts, settings.seed_dir / "source_policies.json")
        catalogue_data = json.loads(catalogue.read_text(encoding="utf-8"))
        projects = {
            r["project_name"]: r["project_id"]
            for r in import_projects(client, scratch, contracts, catalogue_data, settings.seed_dir)
        }
        for name, records in data["construction_status"].items():
            scratch["ai_project_configs"].update_one(
                {"_id": projects[name]}, {"$set": {"construction_status": records}}
            )
        doc_of_source: dict[str, str] = {}
        unlinked = []
        for doc in data["documents"]:
            source = _store(scratch, doc)
            identify_source(client, scratch, contracts, source, focus_project_ids=[projects[doc["project"]]])
            doc_of_source[source["id"]] = doc["id"]
            if not scratch["ai_project_source_links"].count_documents(
                {"source.id": source["id"], "status": {"$in": ["auto_accepted", "accepted"]}}
            ):
                unlinked.append(doc["id"])
        while run_one(scratch, "evaluation-worker", 60) is not None:
            pass
        cluster_origins(client, scratch)
        doc_of_evidence = {
            e["id"]: doc_of_source[e["source"]["id"]]
            for e in scratch["ai_evidence"].find({}, {"id": 1, "source": 1})
            if e["source"]["id"] in doc_of_source
        }
        outputs = _run_agents(scratch, contracts, gateway, projects)
        cost = sum(r.get("estimated_cost_usd") or 0.0 for r in scratch["ai_agent_runs"].find())
        calls = scratch["ai_agent_runs"].count_documents({"returned_model": {"$ne": None}})
        failed = scratch["ai_agent_runs"].count_documents({"outcome": "failed"})
    finally:
        client.drop_database(scratch.name)
    scored = _score(data, outputs, doc_of_evidence)
    return {
        "dataset": data["dataset"],
        "models": {
            "A05/A11 (light)": run_settings.model_light,
            "A06/A07 (routine)": run_settings.model_routine,
        },
        "prompt_versions": {
            "A05": a05.PROMPT_VERSION,
            "A06": a06.PROMPT_VERSION,
            "A07": a07.PROMPT_VERSION,
            "A11": a11.PROMPT_VERSION,
        },
        "documents": len(data["documents"]),
        "unlinked_documents": unlinked,
        "model_calls": calls,
        "failed_tasks": failed,
        "cost_usd": round(cost, 6),
        "elapsed_s": round(time.monotonic() - started, 1),
        **scored,
        "scratch_database_dropped": True,
    }


def _run_agents(
    scratch: Database[dict[str, Any]], contracts: ContractStore, gateway: ModelGateway, projects: dict[str, str]
) -> dict[str, Any]:
    claims: list[dict[str, Any]] = []
    findings: dict[str, list[dict[str, Any]]] = {}
    reviews: list[dict[str, Any]] = []
    drops: dict[str, dict[str, int]] = {"a05": {}, "a06": {}, "a07": {}, "a11": {}}

    def add(agent: str, counts: dict[str, int]) -> None:
        for key, value in counts.items():
            drops[agent][key] = drops[agent].get(key, 0) + value

    for name, project_id in sorted(projects.items()):
        project = scratch["projects"].find_one({"_id": project_id})
        config = scratch["ai_project_configs"].find_one({"_id": project_id})
        assert project is not None and config is not None
        drafts: list[dict[str, Any]] = []
        for task in a05.build_tasks(scratch, project_id):
            out = a05.extract(scratch, gateway, project, config, task, RUN_ID)
            drafts += out["drafts"]
            add("a05", out["drops"])
        verdicts: dict[str, dict[str, Any]] = {}
        for task in a06.build_tasks(scratch, project_id, drafts, None):
            out = a06.verify(scratch, gateway, project, task, RUN_ID)
            verdicts.update(out["verdicts"])
            add("a06", out["fixes"])
        refs = a06.store_claims(scratch, contracts, drafts, verdicts, RUN_ID)
        stored = [scratch["ai_claims"].find_one({"id": r["id"], "revision": r["revision"]}) for r in refs]
        claims += [c for c in stored if c is not None]
        usable, _ = a07.usable_claims(scratch, project_id, refs)
        for task in a07.build_tasks(scratch, project_id, usable):
            out = a07.synthesise(scratch, gateway, project, task, RUN_ID)
            findings.setdefault(name, []).extend(out["drafts"])
            add("a07", out["fixes"])
        for task in a11.build_tasks(scratch, project_id):
            out = a11.curate(scratch, gateway, project, config, task, RUN_ID)
            reviews += out["drafts"]
            add("a11", out["drops"])
    return {"claims": claims, "findings": findings, "reviews": reviews, "backend_drops": drops}


def _score(data: dict[str, Any], outputs: dict[str, Any], doc_of_evidence: dict[str, str]) -> dict[str, Any]:
    by_doc: dict[str, list[dict[str, Any]]] = {}
    for claim in outputs["claims"]:
        for doc_id in {doc_of_evidence.get(e["id"]) for e in claim["supporting_evidence"]} - {None}:
            by_doc.setdefault(str(doc_id), []).append(claim)
    reviews_by_doc: dict[str, list[dict[str, Any]]] = {}
    for review in outputs["reviews"]:
        for doc_id in {doc_of_evidence.get(e["id"]) for e in review["evidence"]} - {None}:
            reviews_by_doc.setdefault(str(doc_id), []).append(review)
    rows = []
    totals = {
        "expected_claims": 0,
        "found_claims": 0,
        "forbidden_claims": 0,
        "extra_claims": 0,
        "flag_checks": 0,
        "flag_passes": 0,
        "verification_checks": 0,
        "verification_passes": 0,
        "review_checks": 0,
        "review_passes": 0,
    }
    for doc in data["documents"]:
        claims = by_doc.get(doc["id"], [])
        found = [any(_rule_matches(c, rule) for c in claims) for rule in doc["expect_claims"]]
        forbidden = [c["statement"] for c in claims if any(_rule_matches(c, r) for r in doc["forbid_claims"])]
        extra = [c for c in claims if not any(_rule_matches(c, r) for r in doc["expect_claims"])]
        row: dict[str, Any] = {
            "id": doc["id"],
            "label": doc["label"],
            "claims": [
                {
                    "statement": c["statement"],
                    "aspect": c["aspect"],
                    "type": c["claim_type"],
                    "polarity": c["polarity"],
                    "perspective": c["perspective"],
                    "verification": c["verification"]["status"],
                    "flags": c["consistency_flags"],
                }
                for c in claims
            ],
            "expected_found": f"{sum(found)}/{len(found)}",
            "forbidden": forbidden,
        }
        totals["expected_claims"] += len(found)
        totals["found_claims"] += sum(found)
        totals["forbidden_claims"] += len(forbidden)
        totals["extra_claims"] += len(extra)
        if doc.get("expect_flags"):
            residents = [c for c in claims if c["perspective"] == "resident_experience"]
            if residents:
                totals["flag_checks"] += 1
                ok = all(set(doc["expect_flags"]) <= set(c["consistency_flags"]) for c in residents)
                totals["flag_passes"] += ok
                row["flag_check"] = ok
        if doc.get("forbid_verification"):
            totals["verification_checks"] += 1
            ok = not any(c["verification"]["status"] in doc["forbid_verification"] for c in claims)
            totals["verification_passes"] += ok
            row["verification_check"] = ok
        if doc.get("expect_verification"):
            totals["verification_checks"] += 1
            ok = any(c["verification"]["status"] in doc["expect_verification"] for c in claims)
            totals["verification_passes"] += ok
            row["verification_check"] = ok
        expect = doc.get("expect_review") or {}
        got = reviews_by_doc.get(doc["id"], [])
        if expect.get("present") is not None:
            totals["review_checks"] += 1
            ok = bool(got) == expect["present"] and (
                not got or "polarity" not in expect or all(r["polarity"] in expect["polarity"] for r in got)
            )
            totals["review_passes"] += ok
            row["review_check"] = ok
        if expect.get("flagged") and got:
            totals["review_checks"] += 1
            ok = all(r["consistency_flags"] for r in got)
            totals["review_passes"] += ok
            row["review_flag_check"] = ok
        row["reviews"] = [{"rendering": r["rendering"], "polarity": r["polarity"], "text": r["text"]} for r in got]
        rows.append(row)
    finding_rows, finding_checks, finding_passes = [], 0, 0
    for name, rules in data.get("findings", {}).items():
        made = outputs["findings"].get(name, [])
        for aspect, kinds in rules.get("expect_kinds", {}).items():
            finding_checks += 1
            ok = any(f["aspect"] == aspect and f["kind"] in kinds for f in made)
            finding_passes += ok
            finding_rows.append({"project": name, "aspect": aspect, "expect": kinds, "ok": ok})
        for aspect, banned in rules.get("forbid_attribution", {}).items():
            finding_checks += 1
            ok = not any(f["aspect"] == aspect and f["attribution"] in banned for f in made)
            finding_passes += ok
            finding_rows.append({"project": name, "aspect": aspect, "forbid": banned, "ok": ok})
        finding_rows.append(
            {
                "project": name,
                "made": [
                    {"aspect": f["aspect"], "kind": f["kind"], "attribution": f["attribution"], "wording": f["wording"]}
                    for f in made
                ],
            }
        )

    def share(passed: int, total: int) -> float | None:
        return round(passed / total, 3) if total else None

    summary = {
        "claim_recall": share(totals["found_claims"], totals["expected_claims"]),
        "forbidden_claims": totals["forbidden_claims"],
        "claims_beyond_labels": totals["extra_claims"],
        "flag_checks": f"{totals['flag_passes']}/{totals['flag_checks']}",
        "verification_checks": f"{totals['verification_passes']}/{totals['verification_checks']}",
        "review_checks": f"{totals['review_passes']}/{totals['review_checks']}",
        "review_accuracy": share(totals["review_passes"], totals["review_checks"]),
        "finding_checks": f"{finding_passes}/{finding_checks}",
    }
    return {
        "summary": summary,
        "totals": totals,
        "backend_drops": outputs["backend_drops"],
        "documents_scored": rows,
        "findings_scored": finding_rows,
    }


def evaluation_record(result: dict[str, Any]) -> dict[str, Any]:
    """EvaluationRun fields for ai_evaluations (the caller adds id and created_at)."""
    note = "synthetic fictional posts labelled with the cases; a routing check, not real-world quality"
    totals = result["totals"]
    n = result["documents"]
    metrics = [
        {
            "name": "a05_claim_recall",
            "value": result["summary"]["claim_recall"],
            "sample_size": totals["expected_claims"],
            "note": note,
        },
        {"name": "a05_forbidden_claims", "value": totals["forbidden_claims"], "sample_size": n, "note": "must be 0"},
        {
            "name": "a05_claims_beyond_labels",
            "value": totals["extra_claims"],
            "sample_size": n,
            "note": "reported, not scored",
        },
        {
            "name": "a06_verification_checks_passed",
            "value": totals["verification_passes"],
            "sample_size": totals["verification_checks"],
            "note": note,
        },
        {
            "name": "a11_review_accuracy",
            "value": result["summary"]["review_accuracy"],
            "sample_size": totals["review_checks"],
            "note": note,
        },
        {
            "name": "cost_usd",
            "value": result["cost_usd"],
            "sample_size": result["model_calls"],
            "note": "estimated from usage and the price table",
        },
        {"name": "failed_tasks", "value": result["failed_tasks"], "sample_size": result["model_calls"], "note": None},
    ]
    return {
        "dataset": {k: result["dataset"][k] for k in ("name", "version", "synthetic")},
        "config": {
            "agent": None,
            "model": json.dumps(result["models"], sort_keys=True),
            "prompt_version": json.dumps(result["prompt_versions"], sort_keys=True),
            "schema_version": a05.SCHEMA_VERSION,
        },
        "status": "completed",
        "metrics": metrics,
    }
