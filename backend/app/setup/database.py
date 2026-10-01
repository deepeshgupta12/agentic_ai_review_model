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


def _payload_validator() -> dict[str, Any]:
    """Erasable source text (payload_ref.store = payload_store). Erasure deletes the document; metadata stays."""
    return {
        "$jsonSchema": {
            "bsonType": "object",
            "additionalProperties": False,
            "required": ["_id", "text", "sha256", "created_at"],
            "properties": {
                "_id": {"bsonType": "string", "minLength": 1},
                "text": {"bsonType": "string"},
                "sha256": {"bsonType": "string", "pattern": "^sha256:[0-9a-f]{64}$"},
                "created_at": {"bsonType": "date"},
            },
        }
    }


def _idempotency_validator() -> dict[str, Any]:
    """Idempotency-Key results (docs/03): same key and body returns the stored result."""
    return {
        "$jsonSchema": {
            "bsonType": "object",
            "additionalProperties": False,
            "required": ["_id", "operation_id", "user_id", "digest", "status_code", "response", "created_at"],
            "properties": {
                "_id": {"bsonType": "string", "pattern": "^[0-9a-f]{64}$"},
                "operation_id": {"bsonType": "string"},
                "user_id": {"bsonType": "string"},
                "digest": {"bsonType": "string", "pattern": "^[0-9a-f]{64}$"},
                "status_code": {"bsonType": "int"},
                "response": {"bsonType": "object"},
                "created_at": {"bsonType": "date"},
            },
        }
    }


def _quota_validator() -> dict[str, Any]:
    """Provider quota windows (app/sources/quota.py)."""
    return {
        "$jsonSchema": {
            "bsonType": "object",
            "required": ["_id", "connector_id", "bucket", "window_start", "window_end", "limit", "used"],
            "properties": {
                "_id": {"bsonType": "string"},
                "connector_id": {"bsonType": "string"},
                "bucket": {"bsonType": "string"},
                "window_start": {"bsonType": "date"},
                "window_end": {"bsonType": "date"},
                "limit": {"bsonType": ["int", "long"], "minimum": 0},
                "used": {"bsonType": ["int", "long"], "minimum": 0},
            },
        }
    }


def _availability_validator() -> dict[str, Any]:
    """The last availability check per source revision and its consecutive 'gone' count (app/sources/lifecycle.py)."""
    return {
        "$jsonSchema": {
            "bsonType": "object",
            "required": ["_id", "gone", "at", "last_outcome"],
            "properties": {
                "_id": {"bsonType": "string"},
                "gone": {"bsonType": ["int", "long"], "minimum": 0},
                "at": {"bsonType": "date"},
                "last_outcome": {"enum": ["present", "gone", "unknown"]},
            },
        }
    }


def _fetch_log_validator() -> dict[str, Any]:
    """One record per fetch decision (docs/06 rule 2): policy basis, robots.txt basis and outcome, never content."""
    return {
        "$jsonSchema": {
            "bsonType": "object",
            "required": ["connector_id", "url", "host", "outcome", "at"],
            "properties": {
                "connector_id": {"bsonType": "string"},
                "url": {"bsonType": "string"},
                "final_url": {"bsonType": ["string", "null"]},
                "host": {"bsonType": "string"},
                "family": {"bsonType": ["string", "null"]},
                "policy_version": {"bsonType": ["int", "long", "null"]},
                "robots": {"bsonType": ["string", "null"]},
                "outcome": {"bsonType": "string"},
                "status_code": {"bsonType": ["int", "long", "null"]},
                "run_id": {"bsonType": ["string", "null"]},
                "at": {"bsonType": "date"},
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
        # Step 04: identity, source links, evidence spans, alias proposals, decisions and evaluations.
        CollectionSpec(
            "ai_sources",
            contracts.mongo_validator(
                "sources.schema.json#/$defs/SourceRevision", id_field=None, extra={"_id": string}
            ),
            [
                IndexSpec("uniq_id_revision", [("id", ASCENDING), ("revision", ASCENDING)], {"unique": True}),
                IndexSpec(
                    "uniq_native_revision",
                    [("connector_id", ASCENDING), ("native_id", ASCENDING), ("revision", ASCENDING)],
                    {"unique": True},
                ),
            ],
        ),
        CollectionSpec("ai_payloads", _payload_validator(), []),
        CollectionSpec(
            "ai_source_policies",
            contracts.mongo_validator("sources.schema.json#/$defs/SourcePolicy"),
            [
                IndexSpec(
                    "uniq_family_version", [("family", ASCENDING), ("policy_version", ASCENDING)], {"unique": True}
                ),
            ],
        ),
        CollectionSpec(
            "ai_project_source_links",
            contracts.mongo_validator("sources.schema.json#/$defs/ProjectSourceLink"),
            [
                IndexSpec(
                    "uniq_segment",
                    [
                        ("project_id", ASCENDING),
                        ("source.id", ASCENDING),
                        ("source.revision", ASCENDING),
                        ("segment_key", ASCENDING),
                    ],
                    {"unique": True},
                ),
                IndexSpec("by_project_status", [("project_id", ASCENDING), ("status", ASCENDING), ("_id", DESCENDING)]),
                IndexSpec("by_matched_alias", [("project_id", ASCENDING), ("match.matched_alias", ASCENDING)]),
                IndexSpec("by_source", [("source.id", ASCENDING), ("source.revision", ASCENDING)]),
            ],
        ),
        CollectionSpec(
            "ai_evidence",
            contracts.mongo_validator("evidence.schema.json#/$defs/Evidence", id_field=None, extra={"_id": string}),
            [
                IndexSpec("uniq_id_revision", [("id", ASCENDING), ("revision", ASCENDING)], {"unique": True}),
                IndexSpec("by_link", [("link_id", ASCENDING)]),
                IndexSpec("by_source", [("source.id", ASCENDING), ("source.revision", ASCENDING)]),
            ],
        ),
        CollectionSpec(
            "ai_alias_proposals",
            contracts.mongo_validator("catalogue.schema.json#/$defs/AliasProposal"),
            [
                IndexSpec(
                    "uniq_project_alias", [("project_id", ASCENDING), ("normalised", ASCENDING)], {"unique": True}
                ),
                IndexSpec("by_project_status", [("project_id", ASCENDING), ("status", ASCENDING), ("_id", DESCENDING)]),
            ],
        ),
        CollectionSpec(
            "ai_review_decisions",
            contracts.mongo_validator("content.schema.json#/$defs/ReviewDecision"),
            [
                IndexSpec(
                    "by_target", [("target.type", ASCENDING), ("target.id", ASCENDING), ("created_at", DESCENDING)]
                )
            ],
        ),
        CollectionSpec(
            "ai_evaluations",
            contracts.mongo_validator("operations.schema.json#/$defs/EvaluationRun"),
            [IndexSpec("by_dataset", [("dataset.name", ASCENDING), ("created_at", DESCENDING)])],
        ),
        CollectionSpec(
            "ai_connector_state",
            contracts.mongo_validator(
                "sources.schema.json#/$defs/ConnectorState", id_field=None, extra={"_id": string}
            ),
            [IndexSpec("by_connector_project", [("connector_id", ASCENDING), ("project_id", ASCENDING)])],
        ),
        CollectionSpec("ai_connector_quota", _quota_validator(), []),
        CollectionSpec(
            "ai_runs",
            contracts.mongo_validator("operations.schema.json#/$defs/WorkflowRun"),
            [
                IndexSpec("by_project_time", [("project_id", ASCENDING), ("_id", DESCENDING)]),
                IndexSpec("by_stage", [("stage", ASCENDING)]),
            ],
        ),
        CollectionSpec(
            "ai_run_events",
            contracts.mongo_validator("api.schema.json#/$defs/RunEvent", id_field="event_id"),
            [IndexSpec("by_run", [("run_id", ASCENDING), ("_id", ASCENDING)])],
        ),
        CollectionSpec(
            "ai_fetch_log",
            _fetch_log_validator(),
            [
                IndexSpec("ttl_at", [("at", ASCENDING)], {"expireAfterSeconds": 90 * 86400}),
                IndexSpec("by_host_time", [("host", ASCENDING), ("at", DESCENDING)]),
            ],
        ),
        CollectionSpec("ai_availability_checks", _availability_validator(), []),
        CollectionSpec(
            "ai_idempotency_keys",
            _idempotency_validator(),
            [IndexSpec("ttl_created_at", [("created_at", ASCENDING)], {"expireAfterSeconds": 7 * 86400})],
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
