"""Context windows and anchor integrity (Step 07.1-07.2; D24, D50).

Every evidence span keeps its exact anchor; the context anchor adds the surrounding words a reviewer needs:
- text: up to CONTEXT_PAD code points on each side of the excerpt, cut back to a sentence end or a space so no
  word is split, inside the same stored text representation;
- speech: from the start of the previous transcript window to the end of the next one, on the original timeline;
- frames: none (a frame stands alone).
A context that adds nothing is null. Context is display metadata derived from the same source revision; it is set
once and never changed.

`anchor_problems` re-derives each anchor from what is stored: the bounds must lie inside the text, the excerpt must
be reproduced exactly and every hash must match. It never trusts the stored excerpt alone.
"""

from __future__ import annotations

from typing import Any

from pymongo import MongoClient
from pymongo.client_session import ClientSession
from pymongo.database import Database

from app import audit
from app.db import run_in_transaction
from app.evidence.context import media_context, text_context
from app.identity.intake import source_text
from app.identity.rules import EVIDENCE_MAX_CHARS
from app.identity.text import sha256_text


def _segments_by_source(db: Database[dict[str, Any]], source: dict[str, Any]) -> list[dict[str, Any]]:
    return list(db["ai_media_segments"].find({"source.id": source["id"], "source.revision": source["revision"]}))


def anchor_problems(
    db: Database[dict[str, Any]], evidence: dict[str, Any], text: str | None, segments: list[dict[str, Any]] | None
) -> list[str]:
    """What is wrong with this evidence's anchors, re-derived from the stored source text or media segments."""
    problems: list[str] = []
    excerpt = evidence.get("excerpt_text")
    anchor, context = evidence["anchor"], evidence.get("context_anchor")
    if excerpt is not None and sha256_text(excerpt) != evidence["excerpt_sha256"]:
        problems.append("excerpt hash does not match the excerpt")
    if anchor["kind"] == "text":
        if anchor["end"] <= anchor["start"]:
            problems.append("text anchor is empty or reversed")
        if anchor["excerpt_sha256"] != evidence["excerpt_sha256"]:
            problems.append("anchor hash differs from the evidence hash")
        if text is not None and excerpt is not None:
            if anchor["end"] > len(text):
                problems.append("text anchor runs past the end of the source text")
            elif text[anchor["start"] : anchor["end"]] != excerpt:
                problems.append("the source text at the anchor is not the excerpt")
        if context is not None:
            if context["kind"] != "text" or not (context["start"] <= anchor["start"] < anchor["end"] <= context["end"]):
                problems.append("context does not contain the anchor")
            elif (
                text is not None
                and excerpt is not None
                and (
                    context["end"] > len(text)
                    or sha256_text(text[context["start"] : context["end"]]) != context["excerpt_sha256"]
                )
            ):
                problems.append("the source text at the context anchor does not match its hash")
    else:
        if anchor["end_ms"] <= anchor["start_ms"]:
            problems.append("time anchor is empty or reversed")
        if segments is not None:
            match = [
                s
                for s in segments
                if s["time"]["start_ms"] == anchor["start_ms"]
                and s["time"]["end_ms"] == anchor["end_ms"]
                and s["modality"] == evidence["modality"]
            ]
            if not match:
                problems.append("no media segment of this modality has the anchor's time")
            elif excerpt is not None:
                payload = db["ai_payloads"].find_one({"_id": match[0]["original_text_ref"]}, {"text": 1})
                if payload is None or payload["text"][:EVIDENCE_MAX_CHARS] != excerpt:
                    problems.append("the media segment's words are not the excerpt")
        if context is not None and (
            context["kind"] != "time"
            or not (context["start_ms"] <= anchor["start_ms"] < anchor["end_ms"] <= context["end_ms"])
        ):
            problems.append("context does not contain the anchor")
    return problems


def backfill_context(client: MongoClient[dict[str, Any]], db: Database[dict[str, Any]]) -> dict[str, int]:
    """Give active evidence without a context its context window, once. Audited as one event."""
    report = {"looked_at": 0, "set": 0, "none_needed": 0}
    updates: list[tuple[str, dict[str, Any]]] = []
    sources: dict[str, Any] = {}
    for evidence in db["ai_evidence"].find({"context_anchor": None, "excerpt_text": {"$type": "string"}}):
        report["looked_at"] += 1
        key = f"{evidence['source']['id']}@{evidence['source']['revision']}"
        if key not in sources:
            source = db["ai_sources"].find_one({"_id": key})
            if source is None:
                continue
            is_media = source["source_kind"] in ("video", "short")
            sources[key] = (
                source,
                None if is_media else source_text(db, source),
                _segments_by_source(db, source) if is_media else None,
            )
        source, text, segments = sources[key]
        context = None
        if evidence["anchor"]["kind"] == "text" and text is not None:
            context = text_context(text, evidence["anchor"]["start"], evidence["anchor"]["end"])
        elif evidence["anchor"]["kind"] == "time" and segments is not None:
            mine = [
                s
                for s in segments
                if s["time"]["start_ms"] == evidence["anchor"]["start_ms"] and s["modality"] == evidence["modality"]
            ]
            context = media_context(segments, mine[0]) if mine else None
        if context is None:
            report["none_needed"] += 1
        else:
            updates.append((evidence["_id"], context))

    def write(session: ClientSession) -> None:
        for evidence_id, context in updates:
            result = db["ai_evidence"].update_one(
                {"_id": evidence_id, "context_anchor": None}, {"$set": {"context_anchor": context}}, session=session
            )
            report["set"] += result.modified_count
        if report["set"]:
            audit.record(
                db,
                "evidence.context_added",
                "evidence",
                "all",
                audit.SYSTEM_ACTOR,
                details=dict(report),
                session=session,
            )

    if updates:
        run_in_transaction(client, write)
    return report
