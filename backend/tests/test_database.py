"""UC-19: database setup, validators, transactions and the LangGraph checkpointer (Step 03.4 acceptance:
setup repeats without duplicates; a transaction commit and abort succeed against the replica set)."""

from __future__ import annotations

import operator
from typing import Annotated, TypedDict

import pytest
from pymongo.errors import WriteError

from app.db import run_in_transaction, utcnow
from app.setup.database import collection_specs, setup_database


def test_setup_is_idempotent(raw_db, contracts):
    first = setup_database(raw_db, contracts)
    assert all(entry["created"] for entry in first["collections"].values())
    second = setup_database(raw_db, contracts)
    assert all(
        not e["created"] and e["validator"] == "unchanged" and not e["indexes_created"]
        for e in second["collections"].values()
    )
    for spec in collection_specs(contracts):
        names = [ix["name"] for ix in raw_db[spec.name].list_indexes()]
        assert len(names) == len(set(names)) == len(spec.indexes) + 1  # plus _id


def test_dry_run_changes_nothing(raw_db, contracts):
    report = setup_database(raw_db, contracts, dry_run=True)
    assert report["dry_run"] and all(e["created"] for e in report["collections"].values())
    assert raw_db.list_collection_names() == []


def test_validator_rejects_a_record_the_contract_rejects(db):
    now = utcnow()
    good = {
        "_id": "usr_01JB0000000000000000000001",
        "email": "a@example.test",
        "display_name": "A",
        "roles": ["analyst"],
        "active": True,
        "password_hash": "$argon2id$v=19$m=1,t=1,p=1$abc$def",
        "created_at": now,
        "updated_at": now,
    }
    db["users"].insert_one(good)
    with pytest.raises(WriteError):
        db["users"].insert_one(
            {**good, "_id": "usr_01JB0000000000000000000002", "email": "b@example.test", "roles": ["superuser"]}
        )
    with pytest.raises(WriteError):
        db["users"].insert_one(
            {**good, "_id": "usr_01JB0000000000000000000003", "email": "c@example.test", "created_at": "2026-09-28"}
        )


def test_unique_email_is_enforced(db):
    from pymongo.errors import DuplicateKeyError

    now = utcnow()
    doc = {
        "email": "same@example.test",
        "display_name": "A",
        "roles": ["analyst"],
        "active": True,
        "password_hash": "$argon2id$x",
        "created_at": now,
        "updated_at": now,
    }
    db["users"].insert_one({"_id": "usr_01JB0000000000000000000004", **doc})
    with pytest.raises(DuplicateKeyError):
        db["users"].insert_one({"_id": "usr_01JB0000000000000000000005", **doc})


def test_transaction_commit(db):
    def work(session):
        db["tx_probe"].insert_one({"_id": "a"}, session=session)
        db["tx_probe"].insert_one({"_id": "b"}, session=session)

    run_in_transaction(db.client, work)
    assert db["tx_probe"].count_documents({}) == 2


def test_transaction_abort_rolls_back_every_write(db):
    db["tx_probe"].insert_one({"_id": "seed"})

    def work(session):
        db["tx_probe"].insert_one({"_id": "c"}, session=session)
        db["tx_probe"].update_one({"_id": "seed"}, {"$set": {"touched": True}}, session=session)
        raise RuntimeError("abort")

    with pytest.raises(RuntimeError):
        run_in_transaction(db.client, work)
    assert db["tx_probe"].count_documents({}) == 1
    assert "touched" not in db["tx_probe"].find_one({"_id": "seed"})


def test_langgraph_checkpoint_saves_and_resumes_across_processes(db):
    from langgraph.checkpoint.mongodb import MongoDBSaver
    from langgraph.graph import END, START, StateGraph

    class State(TypedDict):
        steps: Annotated[list[str], operator.add]

    def build(saver):
        graph = StateGraph(State)
        graph.add_node("collect", lambda s: {"steps": ["collect"]})
        graph.add_node("review", lambda s: {"steps": ["review"]})
        graph.add_edge(START, "collect")
        graph.add_edge("collect", "review")
        graph.add_edge("review", END)
        return graph.compile(checkpointer=saver, interrupt_before=["review"])

    config = {"configurable": {"thread_id": "run_01JB0000000000000000000001"}}
    first = MongoDBSaver(
        db.client, db_name=db.name, checkpoint_collection_name="lg_checkpoints", writes_collection_name="lg_writes"
    )
    build(first).invoke({"steps": []}, config)
    assert build(first).get_state(config).next == ("review",)

    second = MongoDBSaver(
        db.client, db_name=db.name, checkpoint_collection_name="lg_checkpoints", writes_collection_name="lg_writes"
    )
    resumed = build(second).invoke(None, config)
    assert resumed["steps"] == ["collect", "review"]
    assert db["lg_checkpoints"].count_documents({}) >= 2
