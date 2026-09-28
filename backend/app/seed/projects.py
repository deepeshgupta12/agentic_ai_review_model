"""Import the project catalogue from the five-project input file (Steps 03.4 and 04.1, D15, D16, D19, D27).

Used by `python -m app.cli seed-projects` and by POST /v1/projects/import. Safe to
re-run: an existing project is found by its the client ID, else by normalised name
and city; its ID and slug never change. The project record and its configuration are
written in one transaction. An existing configuration is left alone (researchers may
have edited it) except that missing input-derived aliases and the export status record
are added. `seed_status_records` adds the phase and project status records kept in
seed/construction_status.json (I16).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pymongo import MongoClient
from pymongo.client_session import ClientSession
from pymongo.database import Database

from app import audit
from app.contracts import ContractStore
from app.db import run_in_transaction, utcnow
from app.ids import new_id
from app.seed.normalise import match_key, normalise_rera_id, normalise_text, slugify


class SeedError(ValueError):
    pass


def validate_input(data: Any, contracts: ContractStore) -> list[str]:
    return contracts.errors(data, "catalogue.schema.json#/$defs/ProjectInputFile")


def load_input(path: Path, contracts: ContractStore) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    errors = validate_input(data, contracts)
    if errors:
        raise SeedError("project input file is invalid:\n  " + "\n  ".join(errors[:10]))
    return dict(data)


def input_aliases(item: dict[str, Any]) -> list[dict[str, Any]]:
    aliases: list[dict[str, Any]] = []
    seen: set[str] = set()

    def add(text: str, target: dict[str, Any], origin: str) -> None:
        normalised = normalise_text(text)
        if normalised and normalised not in seen:
            seen.add(normalised)
            mode = "standalone" if " " in normalised else "context_required"
            aliases.append(
                {
                    "text": text,
                    "normalised": normalised,
                    "target": target,
                    "mode": mode,
                    "origin": origin,
                    "proposal_id": None,
                }
            )

    project_target = {"kind": "project", "rera_id": None}
    add(item["project_name"], project_target, "input_file")
    for name in item.get("alternate_names", []):
        add(name, project_target, "input_file")
    for rera in item.get("rera_ids", []):
        add(
            rera["registered_name"], {"kind": "phase", "rera_id": normalise_rera_id(rera["id"])}, "rera_registered_name"
        )
    return aliases


def _status_records(item: dict[str, Any], contracts: ContractStore) -> list[dict[str, Any]]:
    ref = item.get("client_ref")
    if not ref:
        return []
    status = contracts.content_rules["export_labels"].get(" ".join(ref["status"].casefold().split()))
    if status is None:
        raise SeedError(
            f"{item['project_name']}: export status {ref['status']!r} has no construction status mapping (D27)"
        )
    return [
        {
            "status": status,
            "applies_to": {"kind": "project", "rera_id": None},
            "basis": "client_export",
            "as_of": ref["supplied_on"],
            "note": None,
        }
    ]


def project_fields(item: dict[str, Any]) -> dict[str, Any]:
    ref = item.get("client_ref")
    return {
        "project_name": item["project_name"],
        "alternate_names": item.get("alternate_names", []),
        "locality": item["locality"],
        "city": item["city"],
        "micromarket": item.get("micromarket"),
        "developer": item.get("developer"),
        "phase": item.get("phase"),
        "rera_registrations": [
            {"id": r["id"], "id_normalised": normalise_rera_id(r["id"]), "registered_name": r["registered_name"]}
            for r in item.get("rera_ids", [])
        ],
        "reference_url": item.get("reference_url"),
        "client_id": ref["project_id"] if ref else None,
        "client_ref": ref,
        "input_schema_version": "1.1",
    }


def _defaults(seed_dir: Path) -> dict[str, Any]:
    items = json.loads((seed_dir / "operating_defaults.json").read_text(encoding="utf-8"))["items"]
    connectors = json.loads((seed_dir / "connectors.json").read_text(encoding="utf-8"))["connectors"]
    return {
        "input_languages": items["input_languages"]["value"],
        "output_locale": items["output_locale"]["value"],
        "refresh": {
            "cadence": items["refresh_cadence"]["value"],
            "lookback_days": items["discovery_lookback_days"]["value"],
        },
        "sources": [{"connector_id": c["id"], "enabled": c["demo_requirement"] != "optional"} for c in connectors],
    }


def seed_projects(
    client: MongoClient[dict[str, Any]],
    db: Database[dict[str, Any]],
    contracts: ContractStore,
    input_path: Path,
    seed_dir: Path,
) -> list[dict[str, Any]]:
    return import_projects(client, db, contracts, load_input(input_path, contracts), seed_dir)


def import_projects(
    client: MongoClient[dict[str, Any]],
    db: Database[dict[str, Any]],
    contracts: ContractStore,
    data: dict[str, Any],
    seed_dir: Path,
    actor: dict[str, Any] = audit.SYSTEM_ACTOR,
    origin: str = "five-project input file",
) -> list[dict[str, Any]]:
    """Create or update the catalogue from a validated input file. Returns one report row per project."""
    defaults = _defaults(seed_dir)
    report: list[dict[str, Any]] = []
    for item in data["projects"]:
        fields = project_fields(item)
        key = match_key(item["project_name"], item["city"])
        aliases = input_aliases(item)
        status_records = _status_records(item, contracts)

        def write(
            session: ClientSession,
            fields: dict[str, Any] = fields,
            key: str = key,
            aliases: list[dict[str, Any]] = aliases,
            status_records: list[dict[str, Any]] = status_records,
            item: dict[str, Any] = item,
        ) -> dict[str, Any]:
            now = utcnow()
            existing = None
            if fields["client_id"]:
                existing = db["projects"].find_one({"client_id": fields["client_id"]}, session=session)
            if existing is None:
                existing = db["projects"].find_one({"match_key": key}, session=session)
            if existing is None:
                project_id = new_id("prj")
                slug = slugify(item["project_name"], item["locality"], item["city"])
                if db["projects"].find_one({"slug": slug}, session=session):
                    raise SeedError(f"slug {slug} is already used; two input projects collide (D19)")
                db["projects"].insert_one(
                    {
                        "_id": project_id,
                        "slug": slug,
                        "match_key": key,
                        **fields,
                        "version": 1,
                        "created_at": now,
                        "updated_at": now,
                    },
                    session=session,
                )
                outcome = "created"
            else:
                project_id, slug = existing["_id"], existing["slug"]
                changed = {k: v for k, v in fields.items() if existing.get(k) != v}
                if changed:
                    db["projects"].update_one(
                        {"_id": project_id},
                        {"$set": {**changed, "match_key": key, "updated_at": now}, "$inc": {"version": 1}},
                        session=session,
                    )
                outcome = "updated" if changed else "unchanged"

            config = db["ai_project_configs"].find_one({"_id": project_id}, session=session)
            if config is None:
                db["ai_project_configs"].insert_one(
                    {
                        "_id": project_id,
                        "project_id": project_id,
                        "version": 1,
                        "aliases": aliases,
                        "construction_status": status_records,
                        "negative_keywords": [],
                        **defaults,
                        "updated_at": now,
                        "updated_by": actor,
                    },
                    session=session,
                )
            else:
                known = {a["normalised"] for a in config["aliases"]}
                new_aliases = [a for a in aliases if a["normalised"] not in known]
                have_export = any(
                    r["basis"] == "client_export" and r["as_of"] == s["as_of"]
                    for r in config["construction_status"]
                    for s in status_records
                )
                new_status = [] if have_export else status_records
                if new_aliases or new_status:
                    db["ai_project_configs"].update_one(
                        {"_id": project_id},
                        {
                            "$push": {"aliases": {"$each": new_aliases}, "construction_status": {"$each": new_status}},
                            "$inc": {"version": 1},
                            "$set": {"updated_at": now, "updated_by": actor},
                        },
                        session=session,
                    )
                    if outcome == "unchanged":
                        outcome = "updated"
            if outcome != "unchanged":
                audit.record(
                    db,
                    f"project.{outcome}",
                    "project",
                    project_id,
                    actor,
                    details={"slug": slug, "source": origin},
                    session=session,
                )
            return {"project_id": project_id, "slug": slug, "project_name": item["project_name"], "outcome": outcome}

        report.append(run_in_transaction(client, write))
    return report


def load_status_records(path: Path, contracts: ContractStore) -> list[dict[str, Any]]:
    """seed/construction_status.json: StatusRecord plus the project slug (I16, D27)."""
    data = json.loads(path.read_text(encoding="utf-8"))
    records: list[dict[str, Any]] = []
    for index, item in enumerate(data["records"]):
        record = {k: v for k, v in item.items() if k != "project_slug"}
        errors = contracts.errors(record, "catalogue.schema.json#/$defs/StatusRecord")
        if errors or not isinstance(item.get("project_slug"), str):
            raise SeedError(f"{path.name} records[{index}] is invalid: {'; '.join(errors) or 'project_slug missing'}")
        records.append(item)
    return records


def seed_status_records(
    client: MongoClient[dict[str, Any]], db: Database[dict[str, Any]], contracts: ContractStore, path: Path
) -> list[dict[str, Any]]:
    """Add each status record to its project's configuration unless an identical record is there."""
    report: list[dict[str, Any]] = []
    for item in load_status_records(path, contracts):
        record = {k: v for k, v in item.items() if k != "project_slug"}

        def write(
            session: ClientSession, item: dict[str, Any] = item, record: dict[str, Any] = record
        ) -> dict[str, Any]:
            project = db["projects"].find_one({"slug": item["project_slug"]}, session=session)
            if project is None:
                raise SeedError(f"{item['project_slug']}: no such project; run seed-projects first")
            target = record["applies_to"]
            if target["kind"] == "phase" and target["rera_id"] not in {
                r["id_normalised"] for r in project["rera_registrations"]
            }:
                raise SeedError(f"{item['project_slug']}: {target['rera_id']} is not one of its RERA registrations")
            config = db["ai_project_configs"].find_one({"_id": project["_id"]}, session=session)
            if config is None:
                raise SeedError(f"{item['project_slug']}: no configuration; run seed-projects first")
            outcome = "unchanged"
            if record not in config["construction_status"]:
                result = db["ai_project_configs"].update_one(
                    {"_id": project["_id"], "version": config["version"]},
                    {
                        "$push": {"construction_status": record},
                        "$inc": {"version": 1},
                        "$set": {"updated_at": utcnow(), "updated_by": audit.SYSTEM_ACTOR},
                    },
                    session=session,
                )
                if result.modified_count != 1:
                    raise SeedError(f"{item['project_slug']}: configuration changed while seeding; run again")
                audit.record(
                    db,
                    "project_config.status_added",
                    "project",
                    project["_id"],
                    audit.SYSTEM_ACTOR,
                    details={"status": record["status"], "applies_to": target["rera_id"] or "project"},
                    session=session,
                )
                outcome = "added"
            return {
                "project_slug": item["project_slug"],
                "applies_to": target["rera_id"] or "project",
                "status": record["status"],
                "outcome": outcome,
            }

        report.append(run_in_transaction(client, write))
    return report
