"""Retrieval benchmark on the labelled synthetic set (Step 07.7; evals/retrieval/v1; D50).

A scratch database gets the fictional catalogue and the labelled posts, through the real intake and identity path
(so links, evidence and eligibility are the real ones); posts marked `withdrawn` are withdrawn and erased. Each query
then runs through `retrieval.search` for its project. Reported:
- recall@10 per query and overall, and by kind (same language, other word form, cross-language);
- wrong-project contamination: results from another project (must be 0);
- ineligible leakage: withdrawn posts returned (must be 0);
- anchors: every returned excerpt is re-derived from its stored source (app.evidence.anchors);
- latency of each search call, p50 and p95, on this machine.
The scratch database is dropped afterwards. Small and synthetic: it shows the baseline behaves as designed, not
how well it retrieves real chatter.
"""

from __future__ import annotations

import json
import secrets
import statistics
from pathlib import Path
from typing import Any

from pymongo import MongoClient

from app.config import Settings
from app.contracts import ContractStore
from app.evidence.anchors import anchor_problems
from app.evidence.retrieval import RETRIEVER, search
from app.identity.intake import source_text, store_text_source
from app.identity.service import identify_source
from app.seed.projects import import_projects
from app.setup.database import setup_database
from app.sources.lifecycle import withdraw
from app.sources.policies import seed_policies
from app.workers.worker import run_one

K = 10
BENCHMARK_ACTOR = {"kind": "user", "user_id": "usr_01K00000000000000000000099", "role": "moderator"}


def _percentile(values: list[float], share: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    return round(ordered[min(len(ordered) - 1, int(share * len(ordered)))], 1)


def run_benchmark(
    client: MongoClient[dict[str, Any]], contracts: ContractStore, settings: Settings, directory: Path, catalogue: Path
) -> dict[str, Any]:
    corpus = json.loads((directory / "corpus.json").read_text(encoding="utf-8"))
    cases = json.loads((directory / "cases.json").read_text(encoding="utf-8"))["cases"]
    scratch = client[f"sy_poc_retrieval_{secrets.token_hex(4)}"]
    try:
        setup_database(scratch, contracts)
        seed_policies(client, scratch, contracts, settings.seed_dir / "source_policies.json")
        data = json.loads(catalogue.read_text(encoding="utf-8"))
        projects = {
            r["project_name"]: r["project_id"]
            for r in import_projects(client, scratch, contracts, data, settings.seed_dir)
        }
        doc_of: dict[str, str] = {}  # source id -> document id
        unlinked = []
        for doc in corpus["documents"]:
            source = store_text_source(
                scratch,
                connector_id="web_fetch",
                native_id=f"https://retrieval.example.test/{doc['id']}",
                canonical_url=f"https://retrieval.example.test/{doc['id']}",
                source_kind="forum_post",
                text=doc["text"],
                policy_family="web_public_pages",
                language=doc["language"],
            )
            identify_source(client, scratch, contracts, source, focus_project_ids=[projects[doc["project"]]])
            doc_of[source["id"]] = doc["id"]
            accepted = {"source.id": source["id"], "project_id": projects[doc["project"]]}
            if not scratch["ai_project_source_links"].count_documents(
                {**accepted, "status": {"$in": ["auto_accepted", "accepted"]}}
            ):
                unlinked.append(doc["id"])  # its link went to review or nowhere: identity, not retrieval
            if doc.get("withdrawn"):
                body = {"scope": "source_all_revisions", "revision": None, "reason": "benchmark: withdrawn post"}
                withdraw(client, scratch, contracts, source["id"], body, BENCHMARK_ACTOR)
        while run_one(scratch, "benchmark-worker", 60) is not None:
            pass
        withdrawn = {d["id"] for d in corpus["documents"] if d.get("withdrawn")}
        project_of = {d["id"]: d["project"] for d in corpus["documents"]}
        rows = []
        latencies: list[float] = []
        contamination = leakage = anchor_errors = 0
        for case in cases:
            result = search(scratch, projects[case["project"]], case["query"], limit=K)
            latencies.append(result["elapsed_ms"])
            found = []
            for item in result["items"]:
                evidence = item["evidence"]
                doc_id = doc_of.get(evidence["source"]["id"], "?")
                found.append(doc_id)
                contamination += int(project_of.get(doc_id) != case["project"])
                leakage += int(doc_id in withdrawn)
                stored = scratch["ai_sources"].find_one(
                    {"id": evidence["source"]["id"], "revision": evidence["source"]["revision"]}
                )
                anchor_errors += int(
                    bool(stored is None or anchor_problems(scratch, evidence, source_text(scratch, stored), None))
                )
            hits = [d for d in case["relevant"] if d in found[:K]]
            rows.append(
                {
                    "id": case["id"],
                    "kind": case["kind"],
                    "query": case["query"],
                    "recall_at_10": round(len(hits) / len(case["relevant"]), 3),
                    "found": found,
                    "missed": [d for d in case["relevant"] if d not in hits],
                    "elapsed_ms": result["elapsed_ms"],
                }
            )
    finally:
        client.drop_database(scratch.name)

    def mean(values: list[float]) -> float | None:
        return round(statistics.mean(values), 3) if values else None

    kinds = sorted({r["kind"] for r in rows})
    return {
        "dataset": {k: corpus["dataset"][k] for k in ("name", "version", "synthetic")},
        "retriever": RETRIEVER,
        "documents": len(corpus["documents"]),
        "queries": len(rows),
        "unlinked_documents": unlinked,
        "recall_at_10": mean([r["recall_at_10"] for r in rows]),
        "recall_at_10_by_kind": {k: mean([r["recall_at_10"] for r in rows if r["kind"] == k]) for k in kinds},
        "queries_by_kind": {k: sum(1 for r in rows if r["kind"] == k) for k in kinds},
        "wrong_project_results": contamination,
        "withdrawn_results": leakage,
        "anchor_errors": anchor_errors,
        "latency_ms_p50": _percentile(latencies, 0.5),
        "latency_ms_p95": _percentile(latencies, 0.95),
        "scratch_database_dropped": True,
        "rows": rows,
    }


def benchmark_record(result: dict[str, Any]) -> dict[str, Any]:
    """EvaluationRun fields for ai_evaluations; the caller adds id and created_at."""
    note = "synthetic fictional posts written alongside the retriever; not real-world retrieval quality"
    n = result["queries"]
    return {
        "dataset": result["dataset"],
        "config": {"agent": None, "model": result["retriever"], "prompt_version": None, "schema_version": None},
        "status": "completed",
        "metrics": [
            {"name": "recall_at_10", "value": result["recall_at_10"], "sample_size": n, "note": note},
            *(
                {
                    "name": f"recall_at_10_{kind}",
                    "value": value,
                    "sample_size": result["queries_by_kind"][kind],
                    "note": note,
                }
                for kind, value in result["recall_at_10_by_kind"].items()
            ),
            {
                "name": "wrong_project_results",
                "value": result["wrong_project_results"],
                "sample_size": n,
                "note": "must be 0",
            },
            {"name": "withdrawn_results", "value": result["withdrawn_results"], "sample_size": n, "note": "must be 0"},
            {"name": "anchor_errors", "value": result["anchor_errors"], "sample_size": n, "note": "must be 0"},
            {
                "name": "latency_ms_p50",
                "value": result["latency_ms_p50"],
                "sample_size": n,
                "note": "search call, this machine",
            },
            {
                "name": "latency_ms_p95",
                "value": result["latency_ms_p95"],
                "sample_size": n,
                "note": "search call, this machine",
            },
        ],
    }
