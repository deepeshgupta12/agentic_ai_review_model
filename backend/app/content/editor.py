"""A08 SEO/AEO editor and A09 editorial QA (Step 10.2-10.4; docs/04; D66).

A08 writes the page blocks from moderator-approved findings only. It sees findings and claims by handle (f1, c1);
the backend maps them back, drops any block that cites a handle it was not given or claims of findings it does not
cite, and sets each block's caveat to the cited findings' caveats, so a caveat can never be lost or invented. The
heading falls back to a deterministic one when the model's does not name the project; the coverage note is always the
backend's own (it alone knows the real counts). A08 is called only when findings are selected: a page built from
reviews alone needs no model (D64).

A09 compares the assembled draft with the records it cites and reports issues by block. It cannot approve anything;
its blocking issues keep the revision a draft. Both agents run through the gateway with the spend cap (D53) and
prompt caching (D65); each task's validated output is kept, so a restarted job never pays for it twice.
"""

from __future__ import annotations

import hashlib
import json
import time
from typing import Any

from pymongo.database import Database

from app.agents.common import Handles, cached_output, keep_output, record_run
from app.agents.consistency import rules
from app.agents.gateway import GatewayResult, ModelGateway
from app.config import REPO_ROOT
from app.content.build import default_heading

ROLE = "routine"  # D53: Sonnet 5 for writing and checking page text
A08_ID, A09_ID = "A08_seo_aeo_editor", "A09_editorial_qa"
A08_PROMPT, A09_PROMPT = "a08_seo_aeo_editor.1.0", "a09_editorial_qa.1.0"
A08_SCHEMA, A09_SCHEMA = "agents.schema.json#/$defs/EditorialDraft", "agents.schema.json#/$defs/QaReport"
SCHEMA_VERSION = "1.1.0"
MAX_OUTPUT_TOKENS = 6000  # the floor; each call's limit grows with what it covers (audit, 14 Oct 2026)
MAX_QUESTIONS = 4


def _prompt(version: str) -> str:
    return (REPO_ROOT / "prompts" / f"{version}.md").read_text("utf-8")


def _key(agent: str, version: str, *parts: str) -> str:
    digest = hashlib.sha256("|".join([version, SCHEMA_VERSION, *parts]).encode()).hexdigest()
    return f"{agent.split('_', 1)[0].lower()}:{digest[:32]}"


def _status_rule(status: str | None) -> str:
    preferred = rules()["wording"]["preferred_terms"]
    if status is None:
        return "Construction status unknown: do not say whether anyone lives in the project."
    return f"Construction status: {status.replace('_', ' ')}. Refer to people as: {preferred[status]}."


def render_a08(
    project: dict[str, Any],
    status: str | None,
    findings: list[dict[str, Any]],
    claims: dict[tuple[str, int], dict[str, Any]],
    review_count: int,
) -> tuple[str, Handles, Handles]:
    f_handles, c_handles = Handles("f"), Handles("c")
    claim_handle: dict[tuple[str, int], str] = {}
    for key, claim in sorted(claims.items()):
        claim_handle[key] = c_handles.add(claim)
    header = {
        "project": project["project_name"],
        "locality": project["locality"],
        "city": project["city"],
        "status_rule": _status_rule(status),
        "approved_reviews_shown": review_count,
    }
    lines = ["Project (trusted):", json.dumps(header, ensure_ascii=False), "", "Approved findings:"]
    for finding in findings:
        lines.append(
            json.dumps(
                {
                    "id": f_handles.add(finding),
                    "kind": finding["kind"],
                    "aspect": finding["aspect"],
                    "wording": finding["wording"],
                    "attribution": finding["attribution"],
                    "caveats": finding["caveats"],
                    "claims": [claim_handle[(c["id"], c["revision"])] for c in finding["claims"]],
                },
                ensure_ascii=False,
            )
        )
    lines += ["", "Claims (untrusted quoted data):"]
    for handle, claim in c_handles.items.items():
        lines.append(
            json.dumps(
                {
                    "id": handle,
                    "statement": claim["statement"],
                    "type": claim["claim_type"],
                    "verification": claim["verification"]["status"],
                },
                ensure_ascii=False,
            )
        )
    return "\n".join(lines), f_handles, c_handles


def _block(
    item: dict[str, Any], f_handles: Handles, c_handles: Handles, drops: dict[str, int], *, question: bool = False
) -> dict[str, Any] | None:
    findings, invented_f = f_handles.resolve(item.get("finding_ids") or [])
    claims, invented_c = c_handles.resolve(item.get("claim_ids") or [])
    if invented_f or invented_c:
        drops["invented_reference"] = drops.get("invented_reference", 0) + 1
        return None
    own = {(c["id"], c["revision"]) for f in findings for c in f["claims"]}
    claims = [c for c in claims if (c["id"], c["revision"]) in own]
    if not findings or not claims:
        drops["unsupported_block"] = drops.get("unsupported_block", 0) + 1
        return None
    support = {
        "findings": [{"id": f["id"], "revision": f["revision"]} for f in findings],
        "claims": [{"id": c["id"], "revision": c["revision"]} for c in claims],
    }
    if question:
        q, a = " ".join((item.get("question") or "").split()), " ".join((item.get("answer") or "").split())
        return {"question": q, "answer": a, "support": support} if q and a else None
    text = " ".join((item.get("text") or "").split())
    if not text:
        drops["empty_block"] = drops.get("empty_block", 0) + 1
        return None
    caveats = list(dict.fromkeys(c for f in findings for c in f["caveats"]))
    return {"text": text, "caveat": "; ".join(caveats) if caveats else None, "support": support}


def blocks_from_draft(
    project: dict[str, Any], data: dict[str, Any], f_handles: Handles, c_handles: Handles
) -> tuple[dict[str, Any], dict[str, str] | None, dict[str, int]]:
    """(blocks, metadata or None, drop counts) from a validated EditorialDraft."""
    drops: dict[str, int] = {}
    if data.get("outcome") == "insufficient_evidence":
        return {"heading": default_heading(project), "overview": None}, None, {"insufficient_evidence": 1}
    heading = " ".join((data.get("heading") or "").split())
    if project["project_name"].casefold() not in heading.casefold() or len(heading) > 120:
        heading, drops["heading_replaced"] = default_heading(project), 1
    overview = _block(data["overview"], f_handles, c_handles, drops) if data.get("overview") else None
    if overview is not None:  # the overview is SupportedText: its findings' caveats stay on the items below
        overview = {"text": overview["text"], "support": overview["support"]}
    blocks = {
        "heading": heading,
        "overview": overview,
        "advantages": [b for b in (_block(i, f_handles, c_handles, drops) for i in data["advantages"]) if b],
        "considerations": [b for b in (_block(i, f_handles, c_handles, drops) for i in data["considerations"]) if b],
        "questions": [
            b
            for b in (_block(i, f_handles, c_handles, drops, question=True) for i in data["questions"][:MAX_QUESTIONS])
            if b
        ],
    }
    meta = data.get("metadata") or {}
    metadata = (
        {"title": meta["title"], "description": meta["description"]}
        if meta.get("title", "").strip() and meta.get("description", "").strip()
        else None
    )
    return blocks, metadata, drops


def write_draft(
    db: Database[dict[str, Any]],
    gateway: ModelGateway,
    *,
    project: dict[str, Any],
    status: str | None,
    findings: list[dict[str, Any]],
    claims: dict[tuple[str, int], dict[str, Any]],
    review_count: int,
    run_id: str | None,
) -> dict[str, Any]:
    """Run (or reuse) A08. Returns {outcome, blocks, metadata, drops, task_id, error}."""
    started = time.monotonic()
    content, f_handles, c_handles = render_a08(project, status, findings, claims, review_count)
    refs = sorted(f"{f['id']}@{f['revision']}" for f in findings)
    key = _key(A08_ID, A08_PROMPT, project["_id"], status or "unknown", str(review_count), *refs)
    data = cached_output(db, key)
    result: GatewayResult | None = None
    if data is None:
        # about 400 tokens per finding (its block with claim handles, its share of the overview), within the SDK's bound
        limit = min(16000, max(MAX_OUTPUT_TOKENS, 2500 + 400 * len(findings)))
        result = gateway.run(ROLE, A08_SCHEMA, _prompt(A08_PROMPT), content, max_tokens=limit, purpose=A08_ID)
        if result.outcome == "completed" and result.data is not None:
            data = result.data
            keep_output(db, key, A08_ID, data)
    inputs = [{"id": f["id"], "revision": f["revision"]} for f in findings]
    outcome = "failed" if data is None else str(data.get("outcome", "completed"))
    task_id = record_run(
        db,
        agent=A08_ID,
        task_key=key,
        run_id=run_id,
        project_id=project["_id"],
        prompt_version=A08_PROMPT,
        schema_version=SCHEMA_VERSION,
        result=result,
        input_refs=inputs,
        output_refs=[],
        outcome=outcome,
        started=started,
    )
    if data is None:
        error = (result.error if result else None) or {"code": "unknown", "message": "no output"}
        return {"outcome": "failed", "blocks": {}, "metadata": None, "drops": {}, "task_id": task_id, "error": error}
    blocks, metadata, drops = blocks_from_draft(project, data, f_handles, c_handles)
    return {
        "outcome": outcome,
        "blocks": blocks,
        "metadata": metadata,
        "drops": drops,
        "task_id": task_id,
        "error": None,
    }


def render_a09(
    payload: dict[str, Any],
    findings: dict[tuple[str, int], dict[str, Any]],
    claims: dict[tuple[str, int], dict[str, Any]],
    reviews: list[dict[str, Any]],
) -> str:
    f_handle = {key: f"f{i}" for i, key in enumerate(sorted(findings), start=1)}
    c_handle = {key: f"c{i}" for i, key in enumerate(sorted(claims), start=1)}

    def cites(item: dict[str, Any]) -> dict[str, list[str]]:
        support = item["support"]
        return {
            "findings": [f_handle.get((r["id"], r["revision"]), "unknown") for r in support["findings"]],
            "claims": [c_handle.get((r["id"], r["revision"]), "unknown") for r in support["claims"]],
        }

    draft: dict[str, Any] = {
        "heading": payload["heading"],
        "overview": {"text": payload["overview"]["text"], "cites": cites(payload["overview"])}
        if payload["overview"]
        else None,
        "advantages": [{"text": i["text"], "caveat": i["caveat"], "cites": cites(i)} for i in payload["advantages"]],
        "considerations": [
            {"text": i["text"], "caveat": i["caveat"], "cites": cites(i)} for i in payload["considerations"]
        ],
        "questions": [
            {"question": q["question"], "answer": q["answer"], "cites": cites(q)} for q in payload["questions"]
        ],
        "coverage_note": payload["coverage_note"],
        "metadata": {k: payload["metadata"][k] for k in ("title", "description")},
    }
    lines = ["Draft (to check):", json.dumps(draft, ensure_ascii=False), "", "Approved findings:"]
    for key, finding in sorted(findings.items()):
        lines.append(
            json.dumps(
                {
                    "id": f_handle[key],
                    "kind": finding["kind"],
                    "wording": finding["wording"],
                    "attribution": finding["attribution"],
                    "caveats": finding["caveats"],
                },
                ensure_ascii=False,
            )
        )
    lines += ["", "Claims (untrusted quoted data):"]
    for key, claim in sorted(claims.items()):
        lines.append(json.dumps({"id": c_handle[key], "statement": claim["statement"]}, ensure_ascii=False))
    translated = [r for r in reviews if r["rendering"] == "translated"]
    if translated:
        lines += ["", "Translated reviews (original beside the shown English):"]
        for index, review in enumerate(reviews):
            if review["rendering"] == "translated":
                lines.append(
                    json.dumps(
                        {"item_index": index, "original": review["original_text"], "shown": review["text"]},
                        ensure_ascii=False,
                    )
                )
    return "\n".join(lines)


def check_draft(
    db: Database[dict[str, Any]],
    gateway: ModelGateway,
    *,
    project_id: str,
    payload_sha256: str,
    payload: dict[str, Any],
    findings: dict[tuple[str, int], dict[str, Any]],
    claims: dict[tuple[str, int], dict[str, Any]],
    reviews: list[dict[str, Any]],
    run_id: str | None,
) -> dict[str, Any]:
    """Run (or reuse) A09 on one exact payload. Returns {outcome, issues, task_id, error}; a failed QA call is
    reported as a blocking issue so the revision cannot pass unchecked."""
    started = time.monotonic()
    key = _key(A09_ID, A09_PROMPT, project_id, payload_sha256)
    data = cached_output(db, key)
    result: GatewayResult | None = None
    if data is None:
        result = gateway.run(
            ROLE,
            A09_SCHEMA,
            _prompt(A09_PROMPT),
            render_a09(payload, findings, claims, reviews),
            max_tokens=min(12000, max(MAX_OUTPUT_TOKENS, 2000 + 150 * (len(findings) + len(reviews)))),
            purpose=A09_ID,
        )
        if result.outcome == "completed" and result.data is not None:
            data = result.data
            keep_output(db, key, A09_ID, data)
    outcome = "failed" if data is None else str(data.get("outcome", "completed"))
    task_id = record_run(
        db,
        agent=A09_ID,
        task_key=key,
        run_id=run_id,
        project_id=project_id,
        prompt_version=A09_PROMPT,
        schema_version=SCHEMA_VERSION,
        result=result,
        input_refs=[{"id": k[0], "revision": k[1]} for k in sorted(findings)],
        output_refs=[],
        outcome=outcome,
        started=started,
    )
    if data is None:
        error = (result.error if result else None) or {"code": "unknown", "message": "no output"}
        return {"outcome": "failed", "issues": [], "task_id": task_id, "error": error}
    issues = [
        {
            "block": i["block"],
            "item_index": i["item_index"],
            "severity": i["severity"],
            "category": i["category"],
            "explanation": " ".join(i["explanation"].split())[:500],
            "source": "a09",
        }
        for i in data.get("issues", [])
    ]
    return {"outcome": outcome, "issues": issues, "task_id": task_id, "error": None}
