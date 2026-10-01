"""UC-39: the source lifecycle (Step 05.6, 05.7; docs/02 retention; journey J12). Fictional sources only."""

from __future__ import annotations

from datetime import timedelta

import pytest

from app.api.routes_sources import source_view as source_contract_view
from app.db import utcnow
from app.errors import ApiError
from app.identity.evidence import usable_for_identity
from app.identity.intake import store_text_source
from app.identity.service import identify_source
from app.sources.lifecycle import NotReady, expire_due, handle_erase, record_check, withdraw
from app.workers.worker import run_one

MODERATOR = {"kind": "user", "user_id": "usr_01K00000000000000000000002", "role": "moderator"}
TEXT = "Visited Quillon Residences in Sector 102 last weekend. The road is still poor."


@pytest.fixture
def linked(db, contracts, fictional):
    source = store_text_source(
        db,
        connector_id="web_fetch",
        native_id="https://nobroker.in/q",
        canonical_url="https://nobroker.in/q",
        source_kind="forum_post",
        text=TEXT,
        policy_family="competitor_portals",
    )
    identify_source(db.client, db, contracts, source, focus_project_ids=[fictional["Quillon Residences"]])
    link = db["ai_project_source_links"].find_one({"source.id": source["id"]})
    assert link["status"] == "auto_accepted"
    return source, link


def lifecycle(db, source):
    return db["ai_sources"].find_one({"_id": source["_id"]})["lifecycle"]


def test_a_single_failure_is_temporary_and_a_restored_fetch_reactivates(db, contracts, linked):
    source, _ = linked
    assert record_check(db.client, db, contracts, source, "unknown") == "unavailable"
    evidence = db["ai_evidence"].find_one({"source.id": source["id"]})
    assert not usable_for_identity(db, evidence), "an unavailable source is not used meanwhile"
    assert record_check(db.client, db, contracts, source, "present") == "active"
    assert usable_for_identity(db, evidence)
    assert db["ai_jobs"].count_documents({"kind": "erase_payloads"}) == 0, "nothing is erased for a temporary failure"


def test_deletion_needs_two_consecutive_gone_checks(db, contracts, linked):
    source, link = linked
    assert record_check(db.client, db, contracts, source, "gone") == "unavailable"
    assert record_check(db.client, db, contracts, source, "gone") == "deleted"
    assert db["ai_jobs"].find_one({"kind": "invalidate_dependencies", "logical_key": {"$regex": link["_id"]}})
    assert db["ai_jobs"].find_one({"kind": "erase_payloads"})


def test_erasure_waits_for_invalidation_then_removes_the_text(db, contracts, linked):
    source, _ = linked
    withdraw(
        db.client,
        db,
        contracts,
        source["id"],
        {"scope": "source_revision", "revision": 1, "reason": "Author asked"},
        MODERATOR,
    )
    erase_job = db["ai_jobs"].find_one({"kind": "erase_payloads"})
    with pytest.raises(NotReady):
        handle_erase(db, erase_job, lambda: "ok")
    while run_one(db, "test-worker", 60) is not None:
        pass
    after = db["ai_sources"].find_one({"_id": source["_id"]})
    assert after["lifecycle"] == "withdrawn" and after["payload_ref"] is None
    assert db["ai_payloads"].count_documents({"_id": source["_id"]}) == 0
    evidence = db["ai_evidence"].find_one({"source.id": source["id"]})
    assert evidence["excerpt_text"] is None and evidence["lifecycle"] == "withdrawn"
    assert contracts.errors(source_contract_view(after), "sources.schema.json#/$defs/SourceRevision") == []
    assert db["ai_audit_events"].find_one({"action": "source.erased"})
    invalidation = db["ai_jobs"].find_one({"kind": "invalidate_dependencies"})
    assert (
        invalidation["status"] == "completed"
        and invalidation["updated_at"] <= db["ai_jobs"].find_one({"kind": "erase_payloads"})["updated_at"]
    ), "invalidation finished before erasure"


def test_withdrawal_rules(db, contracts, linked):
    source, _ = linked
    body = {"scope": "source_revision", "revision": 1, "reason": "Author asked"}
    withdraw(db.client, db, contracts, source["id"], body, MODERATOR)
    again = withdraw(db.client, db, contracts, source["id"], body, MODERATOR)
    assert again["status_path"].endswith("/revisions/1"), "withdrawing twice changes nothing"
    with pytest.raises(ApiError) as missing:
        withdraw(db.client, db, contracts, "src_01K0000000000000000000000Z", body, MODERATOR)
    assert missing.value.status == 404


def test_retention_expires_old_sources_only(db, contracts, linked):
    source, _ = linked
    fresh = store_text_source(
        db,
        connector_id="web_fetch",
        native_id="https://nobroker.in/new",
        canonical_url="https://nobroker.in/new",
        source_kind="forum_post",
        text="A recent post about Tavira Vista in Sector 88.",
        policy_family="competitor_portals",
    )
    db["ai_sources"].update_one({"_id": source["_id"]}, {"$set": {"collected_at": utcnow() - timedelta(days=91)}})
    assert expire_due(db.client, db, contracts) == 1
    assert lifecycle(db, source) == "expired" and lifecycle(db, fresh) == "active"
    assert db["ai_jobs"].find_one({"kind": "erase_payloads", "logical_key": {"$regex": source["id"]}})


def edited(db, contracts, source):
    """Store an edit of the linked page: revision 1 becomes superseded, revision 2 is active."""
    from app.sources.policies import current
    from app.sources.store import Item, store_item

    item = Item(
        connector_id="web_fetch",
        native_id=source["native_id"],
        canonical_url=source["canonical_url"],
        source_kind="forum_post",
        capture_level="full_content",
        title=None,
        text=TEXT + " Edited: the road is now repaired.",
    )
    new = store_item(db, item, current(db, "competitor_portals")).source
    assert lifecycle(db, source) == "superseded" and new["revision"] == 2
    return new


def payloads_of(db, source):
    return db["ai_payloads"].count_documents({"_id": {"$regex": f"^{source['id']}@"}})


def test_withdrawing_a_source_erases_every_revision(db, contracts, linked):
    source, _ = linked
    edited(db, contracts, source)
    body = {"scope": "source_all_revisions", "revision": None, "reason": "Author asked"}
    withdraw(db.client, db, contracts, source["id"], body, MODERATOR)
    while run_one(db, "test-worker", 60) is not None:
        pass
    states = {s["revision"]: s["lifecycle"] for s in db["ai_sources"].find({"id": source["id"]})}
    assert states == {1: "withdrawn", 2: "withdrawn"} and payloads_of(db, source) == 0, "no copy of the text stays"


def test_a_confirmed_deletion_reaches_older_revisions(db, contracts, linked):
    source, _ = linked
    new = edited(db, contracts, source)
    record_check(db.client, db, contracts, new, "gone")
    record_check(db.client, db, contracts, new, "gone")
    while run_one(db, "test-worker", 60) is not None:
        pass
    states = {s["revision"]: s["lifecycle"] for s in db["ai_sources"].find({"id": source["id"]})}
    assert states == {1: "deleted", 2: "deleted"} and payloads_of(db, source) == 0


def test_an_old_superseded_revision_expires_with_retention(db, contracts, linked):
    source, _ = linked
    edited(db, contracts, source)
    db["ai_sources"].update_one({"_id": source["_id"]}, {"$set": {"collected_at": utcnow() - timedelta(days=91)}})
    assert expire_due(db.client, db, contracts) == 1 and lifecycle(db, source) == "expired"


def recollect(db, source, text):
    from app.sources.policies import current
    from app.sources.store import Item, store_item

    item = Item(
        connector_id="web_fetch",
        native_id=source["native_id"],
        canonical_url=source["canonical_url"],
        source_kind="forum_post",
        capture_level="full_content",
        title=None,
        text=text,
    )
    return store_item(db, item, current(db, "competitor_portals"))


def test_a_source_withdrawn_on_request_is_never_collected_again(db, contracts, linked):
    source, _ = linked
    body = {"scope": "source_all_revisions", "revision": None, "reason": "Author asked"}
    withdraw(db.client, db, contracts, source["id"], body, MODERATOR)
    again = recollect(db, source, TEXT)
    assert not again.created and again.source["lifecycle"] == "withdrawn"
    assert db["ai_sources"].count_documents({"id": source["id"]}) == 1


def test_a_system_withdrawal_under_an_old_rule_does_not_block_a_later_collection(db, contracts, linked):
    from app import audit

    source, _ = linked
    body = {"scope": "source_all_revisions", "revision": None, "reason": "policy rule at the time"}
    withdraw(db.client, db, contracts, source["id"], body, audit.SYSTEM_ACTOR)
    again = recollect(db, source, TEXT)
    assert again.created and again.source["revision"] == 2 and again.source["lifecycle"] == "active"
