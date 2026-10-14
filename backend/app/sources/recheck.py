"""Availability re-checks (Step 05.6; D44). Stored web pages and YouTube records are checked again, least recently
checked first, within a per-job budget:

- a temporary failure makes a source unavailable; two consecutive 'gone' results delete it, and its text is
  erased after dependency invalidation (app.sources.lifecycle);
- an edited source becomes a new revision (the old one is superseded and its dependants invalidated) and is linked
  again to the projects its previous revision belonged to, without the identity agent;
- a web page's stated date is corrected, with an audit event, when strict markup extraction no longer supports the
  stored one (D44: dates come only from structured markup);
- a person's review split from a portal or forum page (D68) is checked on its page by its key, never by comparing
  the whole page with it.
Reddit sources are not re-checked (the connector has no deletion check); their policy's retention expires them.
"""

from __future__ import annotations

import logging
from collections import Counter
from typing import Any

from pymongo import MongoClient
from pymongo.client_session import ClientSession
from pymongo.database import Database

from app import audit
from app.config import get_settings
from app.connectors.base import Availability, ProviderError, QuotaExhausted
from app.connectors.portal_reviews import page_reviews, review_item, review_key
from app.connectors.registry import build
from app.contracts import ContractStore, get_contracts
from app.db import run_in_transaction, utcnow
from app.identity.service import identify_in_context, identify_metadata, identify_source
from app.identity.text import nfc, sha256_text
from app.jobs import queue
from app.observability import log_event
from app.sources import policies
from app.sources.lifecycle import CHECKS, record_check
from app.sources.store import Item, dated_for_storage, store_item

logger = logging.getLogger(__name__)
KIND = "check_availability"
RECHECKABLE = ("web_fetch", "youtube_data_api")


def start_recheck(db: Database[dict[str, Any]], project_id: str | None) -> dict[str, Any]:
    """One job per project (or all) per minute; a repeat within the minute returns the same job."""
    key = f"{KIND}:{project_id or 'all'}:{utcnow():%Y%m%dT%H%M}"
    job, created = queue.enqueue(db, KIND, key, project_id=project_id, max_attempts=3)
    return {"job_id": job["_id"], "created": created}


def _candidates(db: Database[dict[str, Any]], project_id: str | None) -> list[dict[str, Any]]:
    query: dict[str, Any] = {
        "connector_id": {"$in": list(RECHECKABLE)},
        "lifecycle": {"$in": ["active", "stale", "unavailable"]},  # latest revisions only
    }
    if project_id:
        linked = db["ai_project_source_links"].distinct(
            "source.id", {"project_id": project_id, "status": {"$ne": "rejected"}}
        )
        query["id"] = {"$in": linked}
    sources = list(db["ai_sources"].find(query, {"author": 0}))
    checked = {c["_id"]: c["at"] for c in db[CHECKS].find({"_id": {"$in": [s["_id"] for s in sources]}}, {"at": 1})}
    return sorted(sources, key=lambda s: (s["_id"] in checked, checked.get(s["_id"]) or 0))


def _linked_projects(db: Database[dict[str, Any]], source: dict[str, Any]) -> list[str]:
    return list(
        db["ai_project_source_links"].distinct(
            "project_id",
            {"source.id": source["id"], "source.revision": source["revision"], "status": {"$ne": "rejected"}},
        )
    )


def _check_review(db: Database[dict[str, Any]], web: Any, source: dict[str, Any], key: str) -> Availability:
    """A person's review split from a portal or forum page (D68): its page is read again and split the same way, and
    the review is looked for by its key (on the portal's full review list too, since a project page shows only some).
    Same words: present; other words: changed (a new revision of the review alone); not shown any more: gone."""
    names = [
        p["project_name"]
        for p in db["projects"].find({"_id": {"$in": _linked_projects(db, source)}}, {"project_name": 1})
    ]
    url, tried = source["canonical_url"], 0
    while url and tried < 2:
        tried += 1
        outcome = web.fetch(url)
        if outcome.status == "gone" and tried == 1:
            return Availability("gone", outcome.reason)
        if outcome.status != "fetched" or not outcome.html:
            return Availability("unknown", f"{outcome.status}: {outcome.reason}")
        found = page_reviews(url, outcome.html, names)
        review = next((r for r in found.reviews if r.key == key), None)
        if review is not None:
            if source.get("content_sha256") == sha256_text(nfc(review.text)):
                return Availability("present", "unchanged")
            parent = source.get("parent") or {}
            page = db["ai_sources"].find_one({"id": parent.get("id")}, sort=[("revision", -1)])
            if page is None:
                return Availability("unknown", "its page is no longer stored")
            return Availability("changed", "the review's words changed", review_item(page, review))
        url = found.more_url
    return Availability("gone", "the page no longer shows this review")


def _store_revision(
    client: MongoClient[dict[str, Any]],
    db: Database[dict[str, Any]],
    contracts: ContractStore,
    source: dict[str, Any],
    item: Item,
) -> bool:
    if source["connector_id"] == "web_fetch":
        resolution = policies.resolve(db, item.canonical_url)
        policy = resolution.policy if resolution.may_collect else None
    else:
        policy = policies.current(db, "youtube")
    if policy is None or not policy["collection_allowed"]:
        return False
    review = review_key(str(source.get("native_id") or "")) is not None
    if not review:  # a split review names its page as parent already
        item.parent = source.get("parent")
    focus = _linked_projects(db, source)

    def write(session: ClientSession) -> Any:
        return store_item(db, item, policy, session)

    stored = run_in_transaction(client, write)
    if not stored.created:
        return False
    if item.capture_level == "metadata_only":
        identify_metadata(client, db, stored.source, item.title or "", focus_project_ids=focus)
    elif review:  # matched on its own words, else it inherits its page's match again (D68)
        page_link = db["ai_project_source_links"].find_one(
            {"source.id": (item.parent or {}).get("id"), "project_id": {"$in": focus}, "status": {"$ne": "rejected"}},
            sort=[("source.revision", -1)],
        )
        identify_in_context(client, db, contracts, stored.source, page_link)
    else:
        identify_source(client, db, contracts, stored.source, focus_project_ids=focus)
    return True


def _correct_date(
    client: MongoClient[dict[str, Any]], db: Database[dict[str, Any]], source: dict[str, Any], item: Item
) -> bool:
    stated = dated_for_storage(item.publication_date)
    if stated == source["publication_date"]:
        return False

    def write(session: ClientSession) -> None:
        db["ai_sources"].update_one({"_id": source["_id"]}, {"$set": {"publication_date": stated}}, session=session)
        audit.record(
            db,
            "source.date_corrected",
            "source",
            source["id"],
            audit.SYSTEM_ACTOR,
            revision=source["revision"],
            details={
                "from": f"{source['publication_date']['status']} {source['publication_date'].get('value')}",
                "to": f"{stated['status']} {stated.get('value')}",
                "basis": "structured markup only (D44)",
            },
            session=session,
        )

    run_in_transaction(client, write)
    return True


def handle_recheck(db: Database[dict[str, Any]], job: dict[str, Any], check: Any) -> str | None:
    """Worker handler for `check_availability` jobs."""
    settings, contracts, client = get_settings(), get_contracts(), db.client
    connectors = {c: build(c, db, settings) for c in RECHECKABLE}
    counts: Counter[str] = Counter()
    candidates = _candidates(db, job.get("project_id"))
    for source in candidates[: settings.recheck_per_job]:
        check()
        connector = connectors.get(source["connector_id"])
        if connector is None:
            counts["not_checked_no_access"] += 1
            continue
        key = review_key(str(source.get("native_id") or ""))
        try:
            result: Availability = (
                _check_review(db, connector, source, key) if key else connector.check_availability(source)
            )
        except QuotaExhausted:
            counts["stopped_at_quota"] += 1
            break
        except ProviderError as exc:
            result = Availability("unknown", f"{exc.code}: {exc.message}")
        after = record_check(
            client, db, contracts, source, "present" if result.state in ("present", "changed") else result.state
        )
        counts[result.state] += 1
        if after == "deleted":
            counts["deleted"] += 1
        if result.item is None:
            continue
        if result.state == "changed" and _store_revision(client, db, contracts, source, result.item):
            counts["new_revisions"] += 1
        elif result.state == "present" and source["connector_id"] == "web_fetch":
            counts["dates_corrected"] += int(_correct_date(client, db, source, result.item))
    counts["left_for_later"] = max(0, len(candidates) - settings.recheck_per_job)
    audit.record(db, "sources.rechecked", "job", str(job["_id"]), audit.SYSTEM_ACTOR, details=dict(counts))
    log_event(logger, "recheck finished", job_id=str(job["_id"]), **dict(counts))
    return None
