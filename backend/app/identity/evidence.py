"""Evidence spans for linked text and media segments (Evidence, D24) and their eligibility for identity work.

Eligibility is computed when used, never stored, by the shared rule in app.evidence.eligibility (D50).
"""

from __future__ import annotations

import re
from typing import Any

from pymongo.client_session import ClientSession
from pymongo.database import Database

from app.db import utcnow
from app.evidence.context import text_context
from app.identity.rules import EVIDENCE_MAX_CHARS
from app.identity.text import sha256_text, text_anchor
from app.ids import new_id


def segment_bounds(segment_key: str, text_length: int) -> tuple[int, int] | None:
    """Code-point bounds of a text segment key, capped for the stored excerpt; None for time segments."""
    if segment_key == "whole":
        start, end = 0, text_length
    elif segment_key.startswith("c:"):
        start, end = (int(x) for x in segment_key[2:].split("-"))
    else:
        return None
    end = min(end, start + EVIDENCE_MAX_CHARS)
    return (start, end) if 0 <= start < end <= text_length else None


def densest_window(text: str, name: str | None) -> tuple[int, int]:
    """The EVIDENCE_MAX_CHARS stretch of a long page that names the project most often, from the start of the line
    of a mention: the opening of a page is mostly its menu (15 Oct 2026: the model read a portal's navigation and
    found no review). The start of the page when the name is not found."""
    if not name:
        return 0, EVIDENCE_MAX_CHARS
    mentions = [m.start() for m in re.finditer(re.escape(name), text, flags=re.IGNORECASE)]
    best, best_count = 0, 0
    for at in mentions:
        line = text.rfind("\n", max(0, at - 300), at)
        start = min(line + 1 if line != -1 else max(0, at - 300), len(text) - EVIDENCE_MAX_CHARS)
        count = sum(1 for m in mentions if start <= m < start + EVIDENCE_MAX_CHARS)
        if count > best_count:
            best, best_count = start, count
    return best, best + EVIDENCE_MAX_CHARS


def create_link_evidence(
    db: Database[dict[str, Any]],
    link: dict[str, Any],
    source: dict[str, Any],
    text: str,
    session: ClientSession | None = None,
) -> dict[str, Any] | None:
    if source.get("capture_level") == "metadata_only":
        return None  # discovery metadata is never evidence (docs/06; Step 05 acceptance)
    bounds = segment_bounds(link["segment_key"], len(text))
    if bounds is None:
        return None
    existing = db["ai_evidence"].find_one({"link_id": link["_id"]}, session=session)
    if existing is not None:
        return existing
    start, end = bounds
    if link["segment_key"] == "whole" and len(text) > EVIDENCE_MAX_CHARS:
        start, end = densest_window(text, (link.get("match") or {}).get("matched_alias"))
    evidence_id = new_id("evd")
    anchor = text_anchor(text, start, end)
    doc = {
        "_id": f"{evidence_id}@1",
        "id": evidence_id,
        "revision": 1,
        "project_id": link["project_id"],
        "source": {"id": source["id"], "revision": source["revision"]},
        "link_id": link["_id"],
        "anchor": anchor,
        "context_anchor": text_context(text, start, end),
        "excerpt_text": text[start:end],
        "excerpt_sha256": anchor["excerpt_sha256"],
        "language": source.get("language") or "und",
        "modality": "text",
        "translation_of": None,
        "origin_cluster": None,
        "policy": source["policy"],
        "lifecycle": "active",
        "created_at": utcnow(),
    }
    db["ai_evidence"].insert_one(doc, session=session)
    return doc


def create_media_evidence(
    db: Database[dict[str, Any]],
    link: dict[str, Any],
    source: dict[str, Any],
    segment: dict[str, Any],
    policy_ref: dict[str, Any],
    session: ClientSession | None = None,
    context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Media evidence for a linked segment (Step 06): a transcript window's words, or a frame's on-screen text or
    description (D49), on the original timeline, governed by the spoken-content policy rather than the video's
    metadata policy."""
    existing = db["ai_evidence"].find_one({"link_id": link["_id"]}, session=session)
    if existing is not None:
        return existing
    excerpt = segment["text"][:EVIDENCE_MAX_CHARS]
    evidence_id = new_id("evd")
    doc = {
        "_id": f"{evidence_id}@1",
        "id": evidence_id,
        "revision": 1,
        "project_id": link["project_id"],
        "source": {"id": source["id"], "revision": source["revision"]},
        "link_id": link["_id"],
        "anchor": segment["time"],
        "context_anchor": context,
        "excerpt_text": excerpt,
        "excerpt_sha256": sha256_text(excerpt),
        "language": segment["language"],
        "modality": segment["modality"],
        "translation_of": None,
        "origin_cluster": None,
        "policy": policy_ref,
        "lifecycle": "active",
        "created_at": utcnow(),
    }
    db["ai_evidence"].insert_one(doc, session=session)
    return doc


def usable_for_identity(
    db: Database[dict[str, Any]], evidence: dict[str, Any], session: ClientSession | None = None
) -> bool:
    """The shared eligibility rule (app.evidence.eligibility), with links still in review allowed."""
    from app.evidence.eligibility import eligibility  # imported here: that module imports identity.links

    return eligibility(db, evidence, for_identity=True, session=session).eligible
