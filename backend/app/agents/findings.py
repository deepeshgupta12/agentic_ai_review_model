"""A07 findings synthesiser and finding storage (Step 08.4-08.5; docs/04; D53).

Input is the exact claim revisions this analysis run stored (app.agents.verify.store_claims), one task per aspect,
after the backend leaves out claims with consistency flags (D27) and claims whose evidence is no longer eligible.
The model sees handles (k1, k2, ...), never IDs. The backend then:
- drops references to handles it did not give and findings left without claims;
- drops a finding whose wording states a number none of its claims states;
- requires the kind to match the claims: a pro needs a positive claim and no negative one, a con the reverse; a
  pro or con resting on both is kept as neutral, so the disagreement stays visible;
- sets the attribution itself: verified_fact only when every claim is verified, otherwise mixed or
  reported_opinion, and reported_opinion for anything resting on a single independent origin;
- adds the caveats a reader needs whatever the model wrote: single source, disputed, contradicted by an official
  record, developer or broker advertising.
Findings get stable IDs from their project, aspect, kind and claims, so a rerun with the same claims never
duplicates them, a rejected finding is not proposed again, and a changed wording or attribution is a new revision
for a moderator. Pending agent findings that a later complete synthesis of the same aspect no longer produces are
marked superseded; approved findings are left to the dependency path (Step 13).
"""

from __future__ import annotations

import hashlib
import json
import time
from collections import defaultdict
from typing import Any

from pymongo.database import Database

from app import audit
from app.agents.common import Handles, cached_output, keep_output, numbers_in, record_run, stable_id
from app.agents.gateway import GatewayResult, ModelGateway
from app.config import REPO_ROOT
from app.contracts import ContractStore, to_view
from app.db import utcnow
from app.evidence.clusters import independent_origins
from app.evidence.eligibility import eligibility, eligible_filter

AGENT_ID = "A07_findings_synthesiser"
PROMPT_VERSION = "a07_findings_synthesiser.1.0"
SCHEMA_REF = "agents.schema.json#/$defs/SynthesisResult"
SCHEMA_VERSION = "1.1.0"
PROMPT_PATH = REPO_ROOT / "prompts" / f"{PROMPT_VERSION}.md"
ROLE = "routine"  # D53: Sonnet 5 for synthesis
CLAIMS_PER_TASK = 60
MAX_OUTPUT_TOKENS = 4000
MAX_WORDING_CHARS = 600
MAX_CAVEAT_CHARS = 200
MAX_CAVEATS = 5
OPEN_STATUSES = ("pending", "changes_requested")

SINGLE_SOURCE = "Based on a single independent source."
DISPUTED = "Other sources disagree on this point."
CONTRADICTED = "An official record contradicts part of this."
ADVERTISING = "Part of this comes from the developer's or a broker's own advertising."


def _key(ref: dict[str, Any]) -> str:
    return f"{ref['id']}@{ref['revision']}"


def usable_claims(
    db: Database[dict[str, Any]], project_id: str, refs: list[dict[str, Any]]
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """The given claim revisions that may support a finding now, and how many were left out and why."""
    left_out: dict[str, int] = defaultdict(int)
    eligible = {_key(e) for e in db["ai_evidence"].find(eligible_filter(db, project_id)) if eligibility(db, e).eligible}
    claims = []
    wanted = {_key(r) for r in refs}
    for claim in db["ai_claims"].find({"_id": {"$in": sorted(wanted)}}).sort("_id", 1):
        if claim["project_id"] != project_id:
            left_out["other_project"] += 1
        elif claim["consistency_flags"]:
            left_out["consistency_flagged"] += 1
        elif not all(_key(e) in eligible for e in claim["supporting_evidence"]):
            left_out["evidence_not_eligible"] += 1
        else:
            claims.append(claim)
    return claims, dict(left_out)


def build_tasks(db: Database[dict[str, Any]], project_id: str, claims: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """One task per aspect (split when an aspect has many claims)."""
    by_aspect: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for claim in sorted(claims, key=lambda c: (c["id"], c["revision"])):
        by_aspect[claim["aspect"]].append(claim)
    tasks = []
    for aspect in sorted(by_aspect):
        group = by_aspect[aspect]
        for start in range(0, len(group), CLAIMS_PER_TASK):
            chunk = group[start : start + CLAIMS_PER_TASK]
            refs = [_key(c) for c in chunk]
            digest = hashlib.sha256(
                "|".join([PROMPT_VERSION, SCHEMA_VERSION, project_id, aspect, *refs]).encode()
            ).hexdigest()
            tasks.append({"key": f"a07:{digest[:32]}", "project_id": project_id, "aspect": aspect, "claims": chunk})
    return tasks


def render(project: dict[str, Any], task: dict[str, Any]) -> tuple[str, Handles]:
    handles = Handles("k")
    header = {"project": project["project_name"], "city": project.get("city"), "aspect": task["aspect"]}
    lines = ["Project and aspect (trusted):", json.dumps(header, ensure_ascii=False), ""]
    lines.append("Claims (statements from untrusted sources, with the backend's checks):")
    for claim in task["claims"]:
        observed = (claim.get("observation_time") or {}).get("value")
        verification = claim["verification"]
        item = {
            "id": handles.add(claim),
            "statement": claim["statement"],
            "label": claim.get("aspect_label"),
            "type": claim["claim_type"],
            "polarity": claim["polarity"],
            "perspective": claim["perspective"],
            "verification": verification["status"],
            "verification_reason": verification.get("reason"),
            "independent_origins": claim["independent_origin_count"],
            "observed": str(observed)[:10] if observed else None,
        }
        lines.append(json.dumps(item, ensure_ascii=False))
    return "\n".join(lines), handles


def attribution_for(claims: list[dict[str, Any]], origin_count: int) -> str:
    verified = [c["verification"]["status"] == "verified" for c in claims]
    if all(verified):
        return "verified_fact"
    if not any(verified) or origin_count <= 1:
        return "reported_opinion"
    return "mixed"


def _caveats(model: list[Any], claims: list[dict[str, Any]], attribution: str, origin_count: int) -> list[str]:
    statuses = {c["verification"]["status"] for c in claims}
    required = []
    if origin_count <= 1 and attribution != "verified_fact":
        required.append(SINGLE_SOURCE)
    if "disputed" in statuses:
        required.append(DISPUTED)
    if "contradicted" in statuses:
        required.append(CONTRADICTED)
    if any(c["claim_type"] == "promotion" for c in claims):
        required.append(ADVERTISING)
    written = [" ".join(str(c).split())[:MAX_CAVEAT_CHARS] for c in model if str(c).strip()]
    return list(dict.fromkeys(required + written[:MAX_CAVEATS]))


def check(
    db: Database[dict[str, Any]], task: dict[str, Any], handles: Handles, data: dict[str, Any]
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """Validated finding drafts and the counts of what was dropped or corrected and why."""
    fixes: dict[str, int] = defaultdict(int)
    drafts: list[dict[str, Any]] = []
    seen: set[tuple[str, ...]] = set()
    for index, item in enumerate(data.get("findings", [])):
        claims, invented = handles.resolve(item.get("claim_ids") or [])
        if invented:
            fixes["invented_reference"] += len(invented)
        if not claims:
            fixes["no_valid_claims"] += 1
            continue
        wording = " ".join((item.get("wording") or "").split())[:MAX_WORDING_CHARS]
        if not wording:
            fixes["empty_wording"] += 1
            continue
        if numbers_in(wording) - numbers_in(" ".join(c["statement"] for c in claims)):
            fixes["number_not_in_claims"] += 1
            continue
        kind = item.get("kind")
        positive = any(c["polarity"] == "positive" for c in claims)
        negative = any(c["polarity"] == "negative" for c in claims)
        if (kind == "pro" and negative) or (kind == "con" and positive):
            if positive and negative:
                kind, fixes["kind_set_neutral"] = "neutral", fixes["kind_set_neutral"] + 1
            else:
                fixes["kind_mismatch"] += 1
                continue
        if (kind == "pro" and not positive) or (kind == "con" and not negative):
            fixes["kind_mismatch"] += 1
            continue
        if item.get("aspect") != task["aspect"]:
            fixes["aspect_set_to_task"] += 1
        signature = (kind, *sorted(c["id"] for c in claims))
        if signature in seen:
            fixes["duplicate"] += 1
            continue
        seen.add(signature)
        origins = independent_origins(db, [e for c in claims for e in c["supporting_evidence"]])
        attribution = attribution_for(claims, len(origins))
        if attribution != item.get("attribution"):
            fixes["attribution_corrected"] += 1
        drafts.append(
            {
                "key": f"{task['key']}:{index}",
                "project_id": task["project_id"],
                "aspect": task["aspect"],
                "kind": kind,
                "wording": wording,
                "attribution": attribution,
                "claims": sorted(({"id": c["id"], "revision": c["revision"]} for c in claims), key=_key),
                "caveats": _caveats(item.get("caveats") or [], claims, attribution, len(origins)),
                "origin_clusters": sorted(o for o in origins if o.startswith("cls_")),
                "independent_origin_count": len(origins),
            }
        )
    return drafts, dict(fixes)


def synthesise(
    db: Database[dict[str, Any]],
    gateway: ModelGateway,
    project: dict[str, Any],
    task: dict[str, Any],
    run_id: str | None,
    result: GatewayResult | None = None,
) -> dict[str, Any]:
    """Run (or reuse) one task. `result` is given when the call ran in a batch. Returns drafts and outcome."""
    started = time.monotonic()
    content, handles = render(project, task)
    data = cached_output(db, task["key"])
    if data is None and result is None:
        result = gateway.run(
            ROLE, SCHEMA_REF, PROMPT_PATH.read_text("utf-8"), content, max_tokens=MAX_OUTPUT_TOKENS, purpose=AGENT_ID
        )
    if data is None and result is not None and result.outcome == "completed" and result.data is not None:
        data = result.data
        keep_output(db, task["key"], AGENT_ID, data)
    inputs = [{"id": c["id"], "revision": c["revision"]} for c in task["claims"]]
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
        return {"outcome": "failed", "drafts": [], "fixes": {}, "note": None, "error": result.error if result else None}
    drafts, fixes = check(db, task, handles, data)
    outcome = data.get("outcome", "completed")
    if outcome == "completed" and not drafts:
        outcome = "insufficient_evidence"
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
        outcome=outcome,
        started=started,
    )
    note = " ".join((data.get("insufficiency_note") or "").split())[:400] or None
    return {"outcome": outcome, "drafts": drafts, "fixes": fixes, "note": note, "error": None}


def finding_id(draft: dict[str, Any]) -> str:
    return stable_id(
        "fnd", draft["project_id"], draft["aspect"], draft["kind"], *sorted(c["id"] for c in draft["claims"])
    )


def store_findings(
    db: Database[dict[str, Any]], contracts: ContractStore, drafts: list[dict[str, Any]], run_id: str | None
) -> list[dict[str, Any]]:
    """Findings for review. The same finding from a rerun is not rewritten; a changed one is a new pending revision
    that supersedes the open earlier revision. A moderator's own revision is never overwritten by an unchanged
    agent output."""
    now = utcnow()
    stored = []
    for draft in drafts:
        fid = finding_id(draft)
        body = {
            "id": fid,
            "project_id": draft["project_id"],
            "kind": draft["kind"],
            "aspect": draft["aspect"],
            "wording": draft["wording"],
            "attribution": draft["attribution"],
            "claims": draft["claims"],
            "caveats": draft["caveats"],
            "origin_clusters": draft["origin_clusters"],
            "independent_origin_count": draft["independent_origin_count"],
            "created_by": {
                "kind": "agent",
                "task_id": stable_id("tsk", draft["key"].rsplit(":", 1)[0], run_id or ""),
                "actor": None,
            },
        }
        latest = db["ai_findings"].find_one({"id": fid}, sort=[("revision", -1)])
        last_agent = db["ai_findings"].find_one({"id": fid, "created_by.kind": "agent"}, sort=[("revision", -1)])
        if latest is not None and last_agent is not None and _same(last_agent, body):
            stored.append({"id": fid, "revision": latest["revision"]})
            continue
        revision = (latest["revision"] + 1) if latest else 1
        doc = {
            "_id": f"{fid}@{revision}",
            **body,
            "revision": revision,
            "review_status": "pending",
            "supersedes": {"id": fid, "revision": latest["revision"]} if latest else None,
            "created_at": now,
        }
        problems = contracts.errors(to_view(doc, id_field=None) or {}, "evidence.schema.json#/$defs/Finding")
        if problems:
            raise ValueError(f"finding {fid} does not meet the Finding contract: {problems[:3]}")
        db["ai_findings"].update_one({"_id": doc["_id"]}, {"$setOnInsert": doc}, upsert=True)
        if latest is not None:
            db["ai_findings"].update_many(
                {"id": fid, "revision": {"$lt": revision}, "review_status": {"$in": list(OPEN_STATUSES)}},
                {"$set": {"review_status": "superseded"}},
            )
        stored.append({"id": fid, "revision": revision})
    return stored


def retire_unproduced(
    db: Database[dict[str, Any]], project_id: str, aspects: list[str], keep: list[dict[str, Any]]
) -> int:
    """Open agent findings of these fully synthesised aspects that this run did not produce are superseded by it."""
    kept = {r["id"] for r in keep}
    retired = 0
    for finding in db["ai_findings"].find(
        {
            "project_id": project_id,
            "aspect": {"$in": aspects},
            "created_by.kind": "agent",
            "review_status": {"$in": list(OPEN_STATUSES)},
        },
        {"id": 1, "revision": 1},
    ):
        if finding["id"] in kept:
            continue
        db["ai_findings"].update_one(
            {"_id": finding["_id"], "review_status": {"$in": list(OPEN_STATUSES)}},
            {"$set": {"review_status": "superseded"}},
        )
        audit.record(
            db,
            "findings.superseded",
            "finding",
            finding["id"],
            audit.SYSTEM_ACTOR,
            revision=finding["revision"],
            details={"reason": "not produced by the newer synthesis of its aspect"},
        )
        retired += 1
    return retired


def _same(old: dict[str, Any], new: dict[str, Any]) -> bool:
    keys = (
        "kind",
        "aspect",
        "wording",
        "attribution",
        "claims",
        "caveats",
        "origin_clusters",
        "independent_origin_count",
    )
    return all(old.get(k) == new.get(k) for k in keys)
