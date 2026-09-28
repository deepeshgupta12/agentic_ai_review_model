"""Idempotent database setup (Step 03.4): collections, validators and indexes.

Validators come from contracts/v1 (ContractStore.mongo_validator), so the database
rejects records the contracts reject. Re-running changes nothing; `dry_run` reports
what would change. Later steps add their collections here.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from pymongo import ASCENDING, DESCENDING
from pymongo.database import Database

from app.contracts import ContractStore
from app.db import utcnow

SCHEMA_VERSION_ID = "contracts-v1"


@dataclass
class IndexSpec:
    name: str
    keys: list[tuple[str, int]]
    options: dict[str, Any] = field(default_factory=dict)


@dataclass
class CollectionSpec:
    name: str
    validator: dict[str, Any]
    indexes: list[IndexSpec]


def _session_validator() -> dict[str, Any]:
    return {
        "$jsonSchema": {
            "bsonType": "object",
            "additionalProperties": False,
            "required": ["_id", "user_id", "csrf_hash", "created_at", "expires_at", "revoked_at"],
            "properties": {
                "_id": {"bsonType": "string", "pattern": "^[0-9a-f]{64}$"},
                "user_id": {"bsonType": "string"},
                "csrf_hash": {"bsonType": "string", "pattern": "^[0-9a-f]{64}$"},
                "created_at": {"bsonType": "date"},
                "expires_at": {"bsonType": "date"},
                "revoked_at": {"bsonType": ["date", "null"]},
            },
        }
    }


def _login_attempt_validator() -> dict[str, Any]:
    return {
        "$jsonSchema": {
            "bsonType": "object",
            "required": ["key", "at", "succeeded"],
            "properties": {
                "key": {"bsonType": "string", "pattern": "^[0-9a-f]{64}$"},
                "at": {"bsonType": "date"},
                "succeeded": {"bsonType": "bool"},
            },
        }
    }


def collection_specs(contracts: ContractStore) -> list[CollectionSpec]:
    string = {"bsonType": "string"}
    return [
        CollectionSpec(
            "users",
            contracts.mongo_validator("operations.schema.json#/$defs/User"),
            [IndexSpec("uniq_email", [("email", ASCENDING)], {"unique": True})],
        ),
        CollectionSpec(
            "sessions",
            _session_validator(),
            [
                IndexSpec("ttl_expires_at", [("expires_at", ASCENDING)], {"expireAfterSeconds": 0}),
                IndexSpec("by_user", [("user_id", ASCENDING)]),
            ],
        ),
        CollectionSpec(
            "login_attempts",
            _login_attempt_validator(),
            [
                IndexSpec("ttl_at", [("at", ASCENDING)], {"expireAfterSeconds": 86400}),
                IndexSpec("by_key_at", [("key", ASCENDING), ("at", DESCENDING)]),
            ],
        ),
        CollectionSpec(
            "projects",
            contracts.mongo_validator("catalogue.schema.json#/$defs/Project", extra={"match_key": string}),
            [
                IndexSpec("uniq_slug", [("slug", ASCENDING)], {"unique": True}),
                IndexSpec("uniq_match_key", [("match_key", ASCENDING)], {"unique": True}),
                IndexSpec(
                    "uniq_client_id",
                    [("client_id", ASCENDING)],
                    {"unique": True, "partialFilterExpression": {"client_id": {"$type": "string"}}},
                ),
            ],
        ),
        CollectionSpec(
            "ai_project_configs",
            contracts.mongo_validator(
                "catalogue.schema.json#/$defs/ProjectConfig", id_field=None, extra={"_id": string}
            ),
            [],
        ),
        CollectionSpec(
            "ai_jobs",
            contracts.mongo_validator(
                "operations.schema.json#/$defs/Job",
                extra={
                    "fencing": {"bsonType": ["int", "long"], "minimum": 0},
                    "cancel_requested": {"bsonType": "bool"},
                },
            ),
            [
                IndexSpec("uniq_logical_key", [("logical_key", ASCENDING)], {"unique": True}),
                IndexSpec(
                    "claimable", [("status", ASCENDING), ("next_attempt_at", ASCENDING), ("created_at", ASCENDING)]
                ),
                IndexSpec("expired_leases", [("status", ASCENDING), ("lease.expires_at", ASCENDING)]),
                IndexSpec("by_project_status", [("project_id", ASCENDING), ("status", ASCENDING)]),
            ],
        ),
        CollectionSpec(
            "ai_audit_events",
            contracts.mongo_validator("operations.schema.json#/$defs/AuditEvent"),
            [
                IndexSpec("by_time", [("at", DESCENDING)]),
                IndexSpec("by_target", [("target.type", ASCENDING), ("target.id", ASCENDING), ("at", DESCENDING)]),
            ],
        ),
        CollectionSpec(
            "ai_agent_runs",
            contracts.mongo_validator("operations.schema.json#/$defs/AgentRun", id_field="task_id"),
            [
                IndexSpec("by_run", [("run_id", ASCENDING)]),
                IndexSpec("by_project_time", [("project_id", ASCENDING), ("created_at", DESCENDING)]),
            ],
        ),
    ]


def setup_database(db: Database[dict[str, Any]], contracts: ContractStore, *, dry_run: bool = False) -> dict[str, Any]:
    """Create or update every collection, validator and index. Returns what was (or would be) done."""
    existing = set(db.list_collection_names())
    report: dict[str, Any] = {"dry_run": dry_run, "collections": {}}
    for spec in collection_specs(contracts):
        entry: dict[str, Any] = {"created": False, "validator": "unchanged", "indexes_created": []}
        if spec.name not in existing:
            entry["created"] = True
            entry["validator"] = "set"
            if not dry_run:
                db.create_collection(
                    spec.name, validator=spec.validator, validationLevel="strict", validationAction="error"
                )
        else:
            options = db[spec.name].options()
            if options.get("validator") != spec.validator:
                entry["validator"] = "updated"
                if not dry_run:
                    db.command(
                        "collMod",
                        spec.name,
                        validator=spec.validator,
                        validationLevel="strict",
                        validationAction="error",
                    )
        present = set() if spec.name not in existing else {ix["name"] for ix in db[spec.name].list_indexes()}
        for index in spec.indexes:
            if index.name not in present:
                entry["indexes_created"].append(index.name)
                if not dry_run:
                    db[spec.name].create_index(index.keys, name=index.name, **index.options)
        report["collections"][spec.name] = entry
    if not dry_run:
        db["schema_migrations"].update_one(
            {"_id": SCHEMA_VERSION_ID},
            {"$set": {"contract_version": "1.0.0", "applied_at": utcnow()}},
            upsert=True,
        )
    return report
