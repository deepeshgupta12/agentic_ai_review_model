"""Store one text source revision and its erasable payload (docs/02 item 1; SourceRevision).

Collectors (Step 05) call this; Step 04 uses it for fixtures and the identity evaluation. A source keeps
one ID across revisions; unchanged content does not create a new revision.
"""

from __future__ import annotations

from typing import Any

from pymongo.client_session import ClientSession
from pymongo.database import Database

from app.db import utcnow
from app.identity.text import nfc, sha256_text
from app.ids import new_id
from app.sources import policies

TEXT_KINDS = {"forum_thread", "forum_post", "article", "blog_post", "news_article", "comment", "registration_record"}


def store_text_source(
    db: Database[dict[str, Any]],
    *,
    connector_id: str,
    native_id: str,
    canonical_url: str,
    source_kind: str,
    text: str,
    policy_family: str,
    title: str | None = None,
    language: str | None = None,
    publication_date: dict[str, Any] | None = None,
    author: dict[str, Any] | None = None,
    parent: dict[str, Any] | None = None,
    session: ClientSession | None = None,
) -> dict[str, Any]:
    if source_kind not in TEXT_KINDS:
        raise ValueError(f"{source_kind} is not a text source kind")
    policy = policies.current(db, policy_family, session=session)
    if policy is None or not policy["collection_allowed"]:
        raise PermissionError(f"the {policy_family} policy does not allow collection")
    text = nfc(text)
    digest = sha256_text(text)
    latest = db["ai_sources"].find_one(
        {"connector_id": connector_id, "native_id": native_id}, sort=[("revision", -1)], session=session
    )
    if latest is not None and latest["content_sha256"] == digest:
        return latest
    source_id = latest["id"] if latest else new_id("src")
    revision = latest["revision"] + 1 if latest else 1
    now = utcnow()
    key = f"{source_id}@{revision}"
    db["ai_payloads"].insert_one({"_id": key, "text": text, "sha256": digest, "created_at": now}, session=session)
    doc = {
        "_id": key,
        "id": source_id,
        "revision": revision,
        "connector_id": connector_id,
        "native_id": native_id,
        "canonical_url": canonical_url,
        "source_kind": source_kind,
        "parent": parent,
        "title": title,
        "author": author,
        "publication_date": publication_date or {"status": "unknown", "value": None, "precision": None, "basis": None},
        "collected_at": now,
        "language": language,
        "capture_level": "full_content",
        "content_sha256": digest,
        "payload_ref": {"store": "payload_store", "key": key},
        "policy": policies.ref_of(policy),
        "lifecycle": "active",
        "media": None,
        "created_at": now,
    }
    db["ai_sources"].insert_one(doc, session=session)
    return doc


def source_text(
    db: Database[dict[str, Any]], source: dict[str, Any], session: ClientSession | None = None
) -> str | None:
    """The stored text of a source revision, or None when it is metadata only or erased."""
    ref = source.get("payload_ref")
    if not ref or ref["store"] != "payload_store":
        return None
    payload = db["ai_payloads"].find_one({"_id": ref["key"]}, session=session)
    return payload["text"] if payload else None
