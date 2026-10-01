"""Storing collected items as source revisions (SourceRevision; docs/02 item 1; Step 05.3, 05.6).

- One source ID across revisions; unchanged content never creates a new revision; a changed one does, and
  the previous revision becomes `superseded` (record_lifecycle: active -> superseded, by the system).
- Metadata-only items (search hits, video metadata) carry no payload and no content hash, and can never
  become evidence.
- Web URLs are normalised before they become native IDs, so the same page found twice is one source.
- The policy version in force is stored with each revision; collection must be allowed by it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from pymongo.client_session import ClientSession
from pymongo.database import Database

from app import audit
from app.db import utcnow
from app.identity.text import nfc, sha256_text
from app.ids import new_id
from app.sources import policies

TRACKING_PARAMS = {"fbclid", "gclid", "igshid", "mc_cid", "mc_eid", "ref", "ref_src", "spm", "si"}
TEXT_KINDS = {"forum_thread", "forum_post", "article", "blog_post", "news_article", "comment", "registration_record"}
UNKNOWN_DATE = {"status": "unknown", "value": None, "precision": None, "basis": None}


def normalise_url(url: str) -> str:
    """Lower-case scheme and host, no fragment, no default port, no tracking parameters, sorted query."""
    parts = urlsplit(url.strip())
    host = (parts.hostname or "").lower()
    port = f":{parts.port}" if parts.port and parts.port not in (80, 443) else ""
    query = urlencode(
        sorted(
            (k, v)
            for k, v in parse_qsl(parts.query, keep_blank_values=True)
            if not k.lower().startswith("utm_") and k.lower() not in TRACKING_PARAMS
        )
    )
    path = parts.path or "/"
    if len(path) > 1 and path.endswith("/"):
        path = path[:-1]
    return urlunsplit((parts.scheme.lower(), host + port, path, query, ""))


def dated_for_storage(value: dict[str, Any]) -> dict[str, Any]:
    """DatedValue with its timestamp as a BSON date (contracts: Timestamp is stored as a date)."""
    stored = dict(value)
    if isinstance(stored.get("value"), str):
        stored["value"] = datetime.fromisoformat(stored["value"].replace("Z", "+00:00"))
    return stored


@dataclass
class Item:
    """What a connector hands to storage. `text` is None for metadata-only items."""

    connector_id: str
    native_id: str
    canonical_url: str
    source_kind: str
    capture_level: str
    title: str | None = None
    text: str | None = None
    publication_date: dict[str, Any] = field(default_factory=lambda: dict(UNKNOWN_DATE))
    language: str | None = None
    author: dict[str, Any] | None = None
    parent: dict[str, Any] | None = None  # SourceRevisionRef of the thread or video
    media: dict[str, Any] | None = None


@dataclass
class Stored:
    source: dict[str, Any]
    created: bool  # a new source or a new revision
    changed: bool  # a new revision of an existing source


def withdrawn_on_request(db: Database[dict[str, Any]], source_id: str, session: ClientSession | None = None) -> bool:
    """A person (moderator or admin) withdrew this source, for example at the author's request. Such a source is
    never collected again. A withdrawal by the system under a policy rule does not block a later collection that
    the current policy allows (D46)."""
    query = {"action": "source.withdrawn", "target.id": source_id, "actor.kind": "user"}
    return db["ai_audit_events"].count_documents(query, limit=1, session=session) > 0


def store_item(
    db: Database[dict[str, Any]], item: Item, policy: dict[str, Any], session: ClientSession | None = None
) -> Stored:
    if not policy["collection_allowed"]:
        raise PermissionError(f"the {policy['family']} policy does not allow collection")
    metadata_only = item.capture_level == "metadata_only"
    if metadata_only == (item.text is not None):
        raise ValueError("metadata-only items carry no text; content items must")
    if item.source_kind in TEXT_KINDS and metadata_only:
        raise ValueError(f"{item.source_kind} is a content kind and needs text")
    text = nfc(item.text) if item.text is not None else None
    digest = sha256_text(text) if text is not None else None
    latest = db["ai_sources"].find_one(
        {"connector_id": item.connector_id, "native_id": item.native_id}, sort=[("revision", -1)], session=session
    )
    if latest is not None and latest["lifecycle"] in ("active", "stale", "unavailable"):
        # A search hit's title varies with the query that found it; that is not an edit of the page (D43).
        same = latest["content_sha256"] == digest and (
            latest["title"] == item.title or item.source_kind == "search_result"
        )
        if same:
            if latest["lifecycle"] == "unavailable":  # fetch restored with unchanged content
                db["ai_sources"].update_one({"_id": latest["_id"]}, {"$set": {"lifecycle": "active"}}, session=session)
                latest["lifecycle"] = "active"
            return Stored(latest, created=False, changed=False)
    if latest is not None and latest["lifecycle"] == "withdrawn" and withdrawn_on_request(db, latest["id"], session):
        return Stored(latest, created=False, changed=False)  # never collected again; callers skip it (D46)
    source_id = latest["id"] if latest else new_id("src")
    revision = latest["revision"] + 1 if latest else 1
    now = utcnow()
    key = f"{source_id}@{revision}"
    if text is not None:
        db["ai_payloads"].insert_one({"_id": key, "text": text, "sha256": digest, "created_at": now}, session=session)
    doc = {
        "_id": key,
        "id": source_id,
        "revision": revision,
        "connector_id": item.connector_id,
        "native_id": item.native_id,
        "canonical_url": item.canonical_url,
        "source_kind": item.source_kind,
        "parent": item.parent,
        "title": item.title,
        "author": item.author,
        "publication_date": dated_for_storage(item.publication_date),
        "collected_at": now,
        "language": item.language,
        "capture_level": item.capture_level,
        "content_sha256": digest,
        "payload_ref": {"store": "payload_store", "key": key} if text is not None else None,
        "policy": policies.ref_of(policy),
        "lifecycle": "active",
        "media": item.media,
        "created_at": now,
    }
    db["ai_sources"].insert_one(doc, session=session)
    changed = latest is not None and latest["lifecycle"] in ("active", "stale", "unavailable")
    if changed:
        assert latest is not None
        db["ai_sources"].update_one({"_id": latest["_id"]}, {"$set": {"lifecycle": "superseded"}}, session=session)
        from app.identity.links import ACTIVE_STATUSES, enqueue_invalidation

        old_links = db["ai_project_source_links"].find(
            {"source.id": source_id, "source.revision": latest["revision"], "status": {"$in": sorted(ACTIVE_STATUSES)}},
            session=session,
        )
        for link in old_links:  # evidence on the old revision is no longer eligible; dependants are re-checked
            enqueue_invalidation(db, link, session)
        audit.record(
            db,
            "source.revised",
            "source",
            source_id,
            audit.SYSTEM_ACTOR,
            revision=revision,
            details={"previous_revision": latest["revision"], "connector": item.connector_id},
            session=session,
        )
    return Stored(doc, created=True, changed=changed)
