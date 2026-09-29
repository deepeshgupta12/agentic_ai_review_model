"""Store one text source revision (kept for Step 04 callers; the general path is app.sources.store)."""

from __future__ import annotations

from typing import Any

from pymongo.client_session import ClientSession
from pymongo.database import Database

from app.sources import policies
from app.sources.store import UNKNOWN_DATE, Item, store_item

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
    item = Item(
        connector_id=connector_id,
        native_id=native_id,
        canonical_url=canonical_url,
        source_kind=source_kind,
        capture_level="full_content",
        title=title,
        text=text,
        publication_date=publication_date or dict(UNKNOWN_DATE),
        language=language,
        author=author,
        parent=parent,
    )
    return store_item(db, item, policy, session).source


def source_text(
    db: Database[dict[str, Any]], source: dict[str, Any], session: ClientSession | None = None
) -> str | None:
    """The stored text of a source revision, or None when it is metadata only or erased."""
    ref = source.get("payload_ref")
    if not ref or ref["store"] != "payload_store":
        return None
    payload = db["ai_payloads"].find_one({"_id": ref["key"]}, session=session)
    return payload["text"] if payload else None
