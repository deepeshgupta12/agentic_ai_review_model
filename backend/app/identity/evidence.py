"""Evidence spans for linked text segments (Evidence, D24) and their eligibility for identity work.

Eligibility is computed when used, never stored: the evidence and its source must be active, the source
policy must allow AI processing and the link must not be rejected or superseded.
"""

from __future__ import annotations

from typing import Any

from pymongo.client_session import ClientSession
from pymongo.database import Database

from app.db import utcnow
from app.identity.rules import EVIDENCE_MAX_CHARS
from app.identity.text import sha256_text, text_anchor
from app.ids import new_id
from app.sources.policies import ai_processing_allowed

UNUSABLE_LINK_STATUSES = {"rejected", "superseded"}


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
        "context_anchor": None,
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
        "context_anchor": None,
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
    if evidence.get("lifecycle") != "active" or not evidence.get("excerpt_text"):
        return False
    link = db["ai_project_source_links"].find_one({"_id": evidence["link_id"]}, session=session)
    if link is None or link["status"] in UNUSABLE_LINK_STATUSES:
        return False
    source = db["ai_sources"].find_one(
        {"id": evidence["source"]["id"], "revision": evidence["source"]["revision"]}, session=session
    )
    if source is None or source["lifecycle"] != "active":
        return False
    return ai_processing_allowed(db, evidence["policy"], session)
