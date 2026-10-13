"""Read-only checks over what the analysis stored (Step 08; `make verify-analysis`). Each row says what was checked,
how many records were looked at and which broke the rule. Nothing is changed."""

from __future__ import annotations

from typing import Any

from pymongo.database import Database

from app.agents.common import numbers_in
from app.agents.findings import attribution_for
from app.agents.reviews import rendering_problem
from app.agents.spend import SpendLedger
from app.config import Settings
from app.contracts import ContractStore, to_view
from app.evidence.clusters import independent_origins
from app.sources.verify import _row


def _key(ref: dict[str, Any]) -> str:
    return f"{ref['id']}@{ref['revision']}"


def verify_analysis(db: Database[dict[str, Any]], contracts: ContractStore, settings: Settings) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    claims = {c["_id"]: c for c in db["ai_claims"].find()}
    findings = list(db["ai_findings"].find())
    reviews = list(db["ai_review_excerpts"].find())
    evidence = {_key(e): e for e in db["ai_evidence"].find({}, {"excerpt_text": 0})}
    decided = {
        (d["target"]["type"], d["target"]["id"], d["target"]["revision"])
        for d in db["ai_review_decisions"].find({"action": "approve", "actor.kind": "user"})
    }

    for name, docs, ref in (
        ("claim", list(claims.values()), "evidence.schema.json#/$defs/Claim"),
        ("finding", findings, "evidence.schema.json#/$defs/Finding"),
        ("review", reviews, "evidence.schema.json#/$defs/ReviewExcerpt"),
    ):
        broken = [d["_id"] for d in docs if contracts.errors(to_view(d, id_field=None) or {}, ref)]
        rows.append(_row(f"every {name} meets its contract", len(docs), broken))

    broken = [
        c["_id"]
        for c in claims.values()
        if any(
            _key(e) not in evidence or evidence[_key(e)]["project_id"] != c["project_id"]
            for e in c["supporting_evidence"] + c["contradicting_evidence"]
        )
    ]
    rows.append(_row("claims cite existing evidence of their own project", len(claims), broken))

    checked = [c for c in claims.values() if c["verification"]["status"] in ("verified", "contradicted")]
    broken = [
        c["_id"]
        for c in checked
        if not c["verification"]["primary_records"]
        or any(
            _key(r) not in evidence or evidence[_key(r)]["policy"]["family"] != "official_records"
            for r in c["verification"]["primary_records"]
        )
    ]
    rows.append(_row("verified or contradicted claims cite an official primary record", len(checked), broken))

    broken = []
    for f in findings:
        cited = [claims.get(_key(c)) for c in f["claims"]]
        present = [c for c in cited if c is not None]
        if len(present) < len(cited) or any(
            c["project_id"] != f["project_id"] or c["consistency_flags"] for c in present
        ):
            broken.append(f["_id"])
    rows.append(_row("findings cite existing, unflagged claims of their own project", len(findings), broken))

    broken = []
    for f in findings:
        present = [c for c in (claims.get(_key(c)) for c in f["claims"]) if c is not None]
        support = [e for c in present for e in c["supporting_evidence"]]
        stated = numbers_in(" ".join(c["statement"] for c in present))
        if f["created_by"]["kind"] == "agent" and (
            f["attribution"] != attribution_for(present, len(independent_origins(db, support)))
            or numbers_in(f["wording"]) - stated
        ):
            broken.append(f["_id"])
    rows.append(_row("agent findings: attribution follows the claims and no number is new", len(findings), broken))

    broken = []
    for r in reviews:
        if any(_key(e) not in evidence or evidence[_key(e)]["source"] != r["source"] for e in r["evidence"]):
            broken.append(r["_id"])
        elif r["text"] is not None and r["original_text"] is not None and r["rendering"] != "translated":
            if rendering_problem(r["rendering"], r["text"], r["original_text"], [r["original_language"]], ""):
                broken.append(r["_id"])
    rows.append(_row("reviews come from one source and keep the author's words", len(reviews), broken))

    approved = [d for d in findings + reviews if d["review_status"] == "approved"]
    broken = [
        d["_id"]
        for d in approved
        if ("finding" if d["_id"].startswith("fnd_") else "review_excerpt", d["id"], d["revision"]) not in decided
        or d.get("consistency_flags")
    ]
    rows.append(
        _row("every approval is a person's decision on that exact revision; no flagged approval", len(approved), broken)
    )

    budget_id = SpendLedger(db, settings).budget_id
    budget = db["ai_model_budget"].find_one({"_id": budget_id}) or {
        "spent_usd": 0.0,
        "limit_usd": settings.model_budget_usd,
    }
    calls = list(db["ai_model_calls"].find({"budget": budget_id}, {"cost_usd": 1}))
    total = sum(c.get("cost_usd") or 0.0 for c in calls)
    spent, limit = budget["spent_usd"], budget["limit_usd"]
    broken = [] if spent <= limit + 1e-9 and abs(total - spent) < 1e-6 else [budget_id]
    rows.append(_row(f"model spend {spent:.4f} of {limit:.2f} USD equals its {len(calls)} ledger entries", 1, broken))
    return rows
