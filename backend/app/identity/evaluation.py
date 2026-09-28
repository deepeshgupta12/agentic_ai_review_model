"""Identity evaluation (Step 04.8): deterministic matching measured on a labelled dataset.

The Step 04 dataset (evals/identity/v1) is synthetic and fictional, and is reported as such. Real labelled
data from collected sources replaces it at Step 12. Metrics count (case, project) pairs; a pair's status is
the strongest of its segments (auto_accepted > needs_review > rejected > not linked). The release target
is at least 98% precision on auto-accepted matches (docs/07); sample sizes are always reported.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.contracts import ContractStore
from app.identity.catalogue import ProjectIdentity, identity_from_records
from app.identity.matching import match_text
from app.identity.rules import RULES_VERSION
from app.seed.normalise import slugify
from app.seed.projects import input_aliases, project_fields

TARGET_AUTO_PRECISION = 0.98
RANK = {"auto_accepted": 3, "needs_review": 2, "rejected": 1, None: 0}


def load_dataset(directory: Path, contracts: ContractStore) -> tuple[dict[str, Any], dict[str, Any]]:
    catalogue = json.loads((directory / "catalogue.json").read_text(encoding="utf-8"))
    problems = contracts.errors(catalogue, "catalogue.schema.json#/$defs/ProjectInputFile")
    if problems:
        raise ValueError("evaluation catalogue is invalid: " + "; ".join(problems[:5]))
    cases = json.loads((directory / "cases.json").read_text(encoding="utf-8"))
    return catalogue, cases


def fictional_identities(catalogue: dict[str, Any]) -> list[ProjectIdentity]:
    """Identities exactly as import would build them, without a database (IDs are the project names)."""
    identities = []
    for item in catalogue["projects"]:
        project = {
            "_id": item["project_name"],
            "slug": slugify(item["project_name"], item["locality"], item["city"]),
            **project_fields(item),
        }
        identities.append(identity_from_records(project, {"aliases": input_aliases(item), "version": 1}))
    return identities


def _ratio(numerator: int, denominator: int) -> float | None:
    return round(numerator / denominator, 4) if denominator else None


def evaluate_dataset(catalogue: dict[str, Any], cases: dict[str, Any]) -> dict[str, Any]:
    identities = fictional_identities(catalogue)
    names = {i.id for i in identities}
    pairs: list[dict[str, Any]] = []
    split_checks: list[bool] = []
    for case in cases["cases"]:
        unknown = [p for p in [*case["focus"], *case["labels"]] if p not in names]
        if unknown:
            raise ValueError(f"{case['id']}: unknown projects {unknown}")
        outcomes = match_text(identities, case["text"], case["focus"])
        best: dict[str, Any] = {}
        for o in outcomes:
            if RANK[o.status] > RANK[best.get(o.project_id, {}).get("status")]:
                best[o.project_id] = {"status": o.status, "phase": o.phase, "segment": o.segment.key}
        if "split" in case["tags"]:
            expected = [p for p, label in case["labels"].items() if label["relevant"]]
            split_checks.append(
                all(any(o.project_id == p and o.segment.key.startswith("c:") for o in outcomes) for p in expected)
            )
        for project in sorted(set(best) | set(case["labels"])):
            label = case["labels"].get(project, {"relevant": False, "phase": None})
            got = best.get(project, {"status": None, "phase": None, "segment": None})
            pairs.append({"case": case["id"], "tags": case["tags"], "project": project, "label": label, **got})

    auto = [p for p in pairs if p["status"] == "auto_accepted"]

    def auto_correct(p: dict[str, Any]) -> bool:
        if p["label"]["relevant"] is not True:
            return False
        phase = p["phase"] or {}
        return not (
            p["label"]["phase"] and phase.get("certainty") == "known" and phase.get("rera_id") != p["label"]["phase"]
        )

    linked_statuses = ("auto_accepted", "needs_review")
    relevant = [p for p in pairs if p["label"]["relevant"] is True]
    linked = [p for p in pairs if p["status"] in linked_statuses]
    phased = [p for p in pairs if p["label"]["phase"] and p["status"] in linked_statuses]
    other_city = [p for p in pairs if "other_city" in p["tags"] and p["label"]["relevant"] is False]
    not_relevant = [p for p in pairs if p["label"]["relevant"] is not True]
    auto_errors = [f"{p['case']}/{p['project']}" for p in auto if not auto_correct(p)]
    wrong_phase = sum(
        (p["phase"] or {}).get("certainty") == "known" and p["phase"]["rera_id"] != p["label"]["phase"] for p in phased
    )
    phase_found = sum((p["phase"] or {}).get("rera_id") == p["label"]["phase"] for p in phased)
    metrics = [
        (
            "auto_accept_precision",
            _ratio(len(auto) - len(auto_errors), len(auto)),
            len(auto),
            f"target {TARGET_AUTO_PRECISION}; errors: {', '.join(auto_errors) or 'none'}",
        ),
        (
            "recall_linked",
            _ratio(sum(p["status"] in linked_statuses for p in relevant), len(relevant)),
            len(relevant),
            "relevant pairs linked as auto-accepted or needs_review",
        ),
        (
            "auto_accept_rate",
            _ratio(sum(p["status"] == "auto_accepted" for p in relevant), len(relevant)),
            len(relevant),
            "share of relevant pairs accepted without a person",
        ),
        (
            "review_share",
            _ratio(sum(p["status"] == "needs_review" for p in linked), len(linked)),
            len(linked),
            "ambiguity: linked pairs sent to review",
        ),
        ("wrong_phase_rate", _ratio(wrong_phase, len(phased)), len(phased), "known phase differs from the label"),
        ("phase_identified", _ratio(phase_found, len(phased)), len(phased), "labelled phase identified"),
        (
            "same_name_other_city_rejected",
            _ratio(sum(p["status"] == "rejected" for p in other_city), len(other_city)),
            len(other_city),
            "same name with another city and nothing of the project's own place",
        ),
        (
            "not_relevant_kept_out_of_auto",
            _ratio(sum(p["status"] != "auto_accepted" for p in not_relevant), len(not_relevant)),
            len(not_relevant),
            "unrelated or undecidable pairs never auto-accepted",
        ),
        (
            "comparison_split_correct",
            _ratio(sum(split_checks), len(split_checks)),
            len(split_checks),
            "each project in a comparison gets its own paragraph segment",
        ),
    ]
    return {
        "dataset": {"name": cases["name"], "version": cases["version"], "synthetic": cases["synthetic"]},
        "config": {"agent": None, "model": None, "prompt_version": None, "schema_version": RULES_VERSION},
        "status": "completed",
        "metrics": [{"name": n, "value": v, "sample_size": s, "note": note} for n, v, s, note in metrics],
        "target_met": (metrics[0][1] or 0) >= TARGET_AUTO_PRECISION,
        "pairs": pairs,
    }
