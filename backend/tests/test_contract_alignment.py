"""UC-22: the backend matches contracts/v1 (D22): the generated API against routes.json, agent-schema
bundling against the Step 02 tooling, naming against the Step 01 validator."""

from __future__ import annotations

import contract_tools  # scripts/contract_tools.py (on sys.path via conftest)
import validate_inputs  # scripts/validate_inputs.py

from app.api.main import create_app
from app.config import REPO_ROOT
from app.seed.normalise import normalise_rera_id, normalise_text, slugify


def test_every_implemented_operation_matches_the_route_table(contracts):
    spec = create_app().openapi()
    routes = {r["operation_id"]: r for r in contracts.routes["routes"]}
    implemented = [
        (path, method.upper(), op) for path, methods in spec["paths"].items() for method, op in methods.items()
    ]
    assert implemented, "no operations generated"
    for path, method, op in implemented:
        assert op["operationId"] in routes, f"{op['operationId']} is not in routes.json"
        route = routes[op["operationId"]]
        assert (route["method"], route["path"]) == (method, path), op["operationId"]


def test_the_backend_bundles_agent_schemas_exactly_like_the_contract_tooling(contracts):
    tooling = contract_tools.Contracts()
    for name in contracts.schemas["agents.schema.json"]["x-agent-outputs"].values():
        ref = f"agents.schema.json#/$defs/{name}"
        assert contracts.bundle(ref) == contract_tools.bundle_schema(tooling, ref), name


def test_mongo_validators_store_timestamps_as_dates(contracts):
    validator = contracts.mongo_validator("operations.schema.json#/$defs/Job")["$jsonSchema"]
    assert validator["properties"]["created_at"] == {"bsonType": "date"}
    assert validator["properties"]["lease"]["anyOf"][0]["properties"]["expires_at"] == {"bsonType": "date"}
    assert "_id" in validator["required"] and "id" not in validator["required"]


def test_a_content_revisions_frozen_payload_keeps_its_timestamps_as_strings(contracts):
    """16 Oct 2026: the validator asked for BSON dates inside the hashed payload and refused every page whose
    reviews had a known date; the payload and manifest are JSON as hashed, so their timestamps are strings."""
    schema = contracts.mongo_validator("content.schema.json#/$defs/ContentRevision")["$jsonSchema"]
    assert schema["properties"]["created_at"] == {"bsonType": "date"}, "records keep BSON dates"
    reviews = schema["properties"]["payload"]["properties"]["reviews"]["items"]["properties"]
    value = reviews["credit"]["properties"]["published"]["properties"]["value"]
    assert all(v.get("bsonType") != "date" for v in value["anyOf"]), value
    assert any(v.get("bsonType") == "string" for v in value["anyOf"]), value
    window = schema["properties"]["payload"]["properties"]["evidence_window"]
    assert "date" not in str(window), window
    manifest = schema["properties"]["manifest"]
    assert "date" not in str(manifest), "the manifest is hashed JSON too"


def test_naming_matches_the_step_01_validator():
    data = validate_inputs.json.loads((REPO_ROOT / "contracts" / "five-project-input-template.json").read_text())
    _, _, registrations = validate_inputs.validate_projects(data)
    for project, registration in zip(data["projects"], registrations, strict=True):
        assert slugify(project["project_name"], project["locality"], project["city"]) == registration["slug"]
        assert normalise_text(project["project_name"]) == registration["search_names"][0]
        assert [normalise_rera_id(r["id"]) for r in project["rera_ids"]] == registration["rera_ids"]


def test_every_operation_in_the_route_table_is_implemented(contracts):
    """The other direction (audit, 14 Oct 2026: receiveWebhook was in the table with no route)."""
    implemented = {op["operationId"] for methods in create_app().openapi()["paths"].values() for op in methods.values()}
    missing = [r["operation_id"] for r in contracts.routes["routes"] if r["operation_id"] not in implemented]
    assert missing == []
