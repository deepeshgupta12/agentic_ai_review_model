"""A06 evidence verifier and claim storage (Step 08.3-08.4; docs/04; D53).

Facts and allegations are checked against what the backend supplies, never against model memory:
- primary records: the project's eligible official-registry evidence (HRERA records, D53);
- other evidence: the nearest eligible evidence of the same project from retrieval (Step 07), excluding the claim's
  own evidence, as candidates that may support or contradict it.
The model gives a verdict per claim handle. The backend then:
- accepts `verified` and `contradicted` only with a cited primary record it supplied; otherwise the claim stays
  `unverified` (or `disputed` when contradicting evidence was cited);
- turns a contradiction cited only from non-primary evidence into `disputed`: posts never contradict a fact;
- drops handles it did not give and a claim's own evidence cited against it;
- never lets a model mark a fact `not_applicable`.
Opinions and promotions are attributed, never verified. Flagged claims (D27) are not verified: they stay out of
findings until a moderator resolves them. Claims are then stored with stable IDs; a later run that changes a claim's
verification stores a new revision.
"""

from __future__ import annotations

import hashlib
import json
import time
from collections import defaultdict
from typing import Any

from pymongo.database import Database

from app.agents.common import Handles, cached_output, keep_output, record_run, stable_id
from app.agents.gateway import GatewayResult, ModelGateway
from app.config import REPO_ROOT
from app.contracts import ContractStore, to_view
from app.db import utcnow
from app.embeddings.client import Embedder
from app.evidence.clusters import independent_origins
from app.evidence.eligibility import eligible_filter
from app.evidence.retrieval import search

AGENT_ID = "A06_evidence_verifier"
PROMPT_VERSION = "a06_evidence_verifier.1.0"
SCHEMA_REF = "agents.schema.json#/$defs/VerificationResult"
SCHEMA_VERSION = "1.1.0"
PROMPT_PATH = REPO_ROOT / "prompts" / f"{PROMPT_VERSION}.md"
ROLE = "routine"  # D53: Sonnet 5 for verification
CLAIMS_PER_TASK = 10
CANDIDATES_PER_CLAIM = 3
CANDIDATE_CHARS = 500
MAX_OUTPUT_TOKENS = 3000
MAX_REASON_CHARS = 400


def _ref(evidence: dict[str, Any]) -> dict[str, Any]:
    return {"id": evidence["id"], "revision": evidence["revision"]}


def _key(ref: dict[str, Any]) -> str:
    return f"{ref['id']}@{ref['revision']}"


def primary_records(db: Database[dict[str, Any]], project_id: str) -> list[dict[str, Any]]:
    return list(
        db["ai_evidence"].find({**eligible_filter(db, project_id), "policy.family": "official_records"}).sort("_id", 1)
    )


def build_tasks(
    db: Database[dict[str, Any]], project_id: str, drafts: list[dict[str, Any]], embedder: Embedder | None
) -> list[dict[str, Any]]:
    """Facts and allegations in tasks of CLAIMS_PER_TASK, ordered by aspect so related claims share a task."""
    to_check = sorted(
        (d for d in drafts if d["claim_type"] in ("fact", "allegation") and not d["consistency_flags"]),
        key=lambda d: (d["aspect"], d["key"]),
    )
    records = primary_records(db, project_id)
    tasks = []
    for start in range(0, len(to_check), CLAIMS_PER_TASK):
        chunk = to_check[start : start + CLAIMS_PER_TASK]
        candidates: dict[str, dict[str, Any]] = {}
        for draft in chunk:
            own = {_key(r) for r in draft["supporting_evidence"]}
            found = search(db, project_id, draft["statement"], limit=CANDIDATES_PER_CLAIM + len(own), embedder=embedder)
            for item in found["items"]:
                evidence = item["evidence"]
                if _key(evidence) not in own and evidence["policy"]["family"] != "official_records":
                    candidates.setdefault(_key(evidence), evidence)
        refs = sorted([d["key"] for d in chunk] + [f"e:{k}" for k in candidates] + [f"r:{_key(r)}" for r in records])
        digest = hashlib.sha256("|".join([PROMPT_VERSION, SCHEMA_VERSION, project_id, *refs]).encode()).hexdigest()
        tasks.append(
            {
                "key": f"a06:{digest[:32]}",
                "project_id": project_id,
                "claims": chunk,
                "records": records,
                "candidates": [candidates[k] for k in sorted(candidates)],
            }
        )
    return tasks


def render(
    db: Database[dict[str, Any]], project: dict[str, Any], task: dict[str, Any]
) -> tuple[str, dict[str, Handles]]:
    claims, records, others = Handles("c"), Handles("r"), Handles("e")
    evidence_text = {
        _key(e): e
        for e in db["ai_evidence"].find(
            {"id": {"$in": sorted({r["id"] for d in task["claims"] for r in d["supporting_evidence"]})}}
        )
    }
    lines = ["Project (trusted):", json.dumps({"project": project["project_name"], "city": project.get("city")}), ""]
    lines.append("Claims (from untrusted evidence):")
    for draft in task["claims"]:
        own = [(evidence_text.get(_key(r)) or {}).get("excerpt_text", "")[:600] for r in draft["supporting_evidence"]]
        lines.append(
            json.dumps(
                {
                    "id": claims.add(draft),
                    "statement": draft["statement"],
                    "aspect": draft["aspect"],
                    "type": draft["claim_type"],
                    "from_evidence": own,
                },
                ensure_ascii=False,
            )
        )
    lines += ["", "Primary records (official registry, dated; untrusted text):"]
    for record in task["records"]:
        lines.append(json.dumps({"id": records.add(record), "text": record["excerpt_text"]}, ensure_ascii=False))
    lines += ["", "Other evidence (untrusted quoted data):"]
    for evidence in task["candidates"]:
        lines.append(
            json.dumps(
                {"id": others.add(evidence), "text": (evidence["excerpt_text"] or "")[:CANDIDATE_CHARS]},
                ensure_ascii=False,
            )
        )
    return "\n".join(lines), {"c": claims, "r": records, "e": others}


def check(
    task: dict[str, Any], handles: dict[str, Handles], data: dict[str, Any]
) -> tuple[dict[str, dict[str, Any]], dict[str, int]]:
    """Verification per draft key, after the backend rules; counts of what was corrected."""
    fixes: dict[str, int] = defaultdict(int)
    out: dict[str, dict[str, Any]] = {}
    for verdict in data.get("verdicts", []):
        found, _ = handles["c"].resolve([verdict.get("claim_id", "")])
        if not found:
            fixes["unknown_claim"] += 1
            continue
        draft = found[0]
        records, bad_records = handles["r"].resolve(verdict.get("primary_record_ids") or [])
        against, bad_against = handles["e"].resolve(verdict.get("contradicting_evidence_ids") or [])
        if bad_records or bad_against:
            fixes["invented_reference"] += len(bad_records) + len(bad_against)
        own = {_key(r) for r in draft["supporting_evidence"]}
        against = [e for e in against if _key(e) not in own]
        status = verdict.get("status", "unverified")
        if status == "not_applicable":
            status, fixes["not_applicable_for_a_fact"] = "unverified", fixes["not_applicable_for_a_fact"] + 1
        if status in ("verified", "contradicted") and not records:
            fixes[f"{status}_without_a_primary_record"] += 1
            status = "disputed" if (status == "contradicted" and against) else "unverified"
        if status == "disputed" and not against:
            fixes["disputed_without_evidence"] += 1
            status = "unverified"
        out[draft["key"]] = {
            "status": status,
            "primary_records": [_ref(r) for r in records] if status in ("verified", "contradicted") else [],
            "contradicting": [_ref(e) for e in against],
            "reason": " ".join((verdict.get("reason") or "").split())[:MAX_REASON_CHARS] or None,
        }
    return out, dict(fixes)


def verify(
    db: Database[dict[str, Any]],
    gateway: ModelGateway,
    project: dict[str, Any],
    task: dict[str, Any],
    run_id: str | None,
    result: GatewayResult | None = None,
) -> dict[str, Any]:
    started = time.monotonic()
    content, handles = render(db, project, task)
    data = cached_output(db, task["key"])
    if data is None and result is None:
        result = gateway.run(
            ROLE, SCHEMA_REF, PROMPT_PATH.read_text("utf-8"), content, max_tokens=MAX_OUTPUT_TOKENS, purpose=AGENT_ID
        )
    if data is None and result is not None and result.outcome == "completed" and result.data is not None:
        data = result.data
        keep_output(db, task["key"], AGENT_ID, data)
    inputs = [_ref(r) for r in task["records"]] + [_ref(e) for e in task["candidates"]]
    if data is None:
        record_run(
            db,
            agent=AGENT_ID,
            task_key=task["key"],
            run_id=run_id,
            project_id=task["project_id"],
            prompt_version=PROMPT_VERSION,
            schema_version=SCHEMA_VERSION,
            result=result,
            input_refs=inputs,
            output_refs=[],
            outcome="failed",
            started=started,
        )
        return {"outcome": "failed", "verdicts": {}, "fixes": {}, "error": result.error if result else None}
    verdicts, fixes = check(task, handles, data)
    record_run(
        db,
        agent=AGENT_ID,
        task_key=task["key"],
        run_id=run_id,
        project_id=task["project_id"],
        prompt_version=PROMPT_VERSION,
        schema_version=SCHEMA_VERSION,
        result=result,
        input_refs=inputs,
        output_refs=[],
        outcome=data.get("outcome", "completed"),
        started=started,
    )
    return {"outcome": data.get("outcome", "completed"), "verdicts": verdicts, "fixes": fixes, "error": None}


def store_claims(
    db: Database[dict[str, Any]],
    contracts: ContractStore,
    drafts: list[dict[str, Any]],
    verdicts: dict[str, dict[str, Any]],
    run_id: str | None,
) -> list[dict[str, Any]]:
    """Claims with stable IDs. Unchanged claims are not rewritten; a changed verification is a new revision."""
    now = utcnow()
    stored = []
    for draft in drafts:
        claim_id = stable_id("clm", draft["key"])
        verdict = verdicts.get(draft["key"]) or {
            "status": draft["verification_status"],
            "primary_records": [],
            "contradicting": [],
            "reason": "Not verified: flagged for review (D27)"
            if draft["consistency_flags"] and draft["verification_status"] == "unverified"
            else None,
        }
        origins = independent_origins(db, draft["supporting_evidence"])
        body = {
            "id": claim_id,
            "project_id": draft["project_id"],
            "aspect": draft["aspect"],
            "aspect_label": draft["aspect_label"],
            "claim_type": draft["claim_type"],
            "polarity": draft["polarity"],
            "perspective": draft["perspective"],
            "consistency_flags": draft["consistency_flags"],
            "statement": draft["statement"],
            "observation_time": draft["observation_time"],
            "supporting_evidence": draft["supporting_evidence"],
            "contradicting_evidence": verdict["contradicting"],
            "verification": {
                "status": verdict["status"],
                "primary_records": verdict["primary_records"],
                "checked_at": now if verdict["status"] not in ("not_applicable",) else None,
                "reason": verdict["reason"],
            },
            "origin_clusters": sorted(o for o in origins if o.startswith("cls_")),
            "independent_origin_count": len(origins),
            "confidence": {"value": None, "calibration_ref": None},
            "created_by_task": stable_id("tsk", draft["key"].rsplit(":", 1)[0], run_id or ""),
        }
        latest = db["ai_claims"].find_one({"id": claim_id}, sort=[("revision", -1)])
        if latest is not None and _same(latest, body):
            stored.append({"id": claim_id, "revision": latest["revision"]})
            continue
        revision = (latest["revision"] + 1) if latest else 1
        doc = {"_id": f"{claim_id}@{revision}", **body, "revision": revision, "created_at": now}
        view = to_view(doc, id_field=None) or {}
        problems = contracts.errors(view | {"id": claim_id}, "evidence.schema.json#/$defs/Claim")
        if problems:
            raise ValueError(f"claim {claim_id} does not meet the Claim contract: {problems[:3]}")
        db["ai_claims"].update_one({"_id": doc["_id"]}, {"$setOnInsert": doc}, upsert=True)
        stored.append({"id": claim_id, "revision": revision})
    return stored


def _same(old: dict[str, Any], new: dict[str, Any]) -> bool:
    keys = (
        "statement",
        "claim_type",
        "polarity",
        "perspective",
        "consistency_flags",
        "contradicting_evidence",
        "supporting_evidence",
    )
    if any(old.get(k) != new.get(k) for k in keys):
        return False
    a, b = old.get("verification") or {}, new["verification"]
    return a.get("status") == b["status"] and a.get("primary_records") == b["primary_records"]
