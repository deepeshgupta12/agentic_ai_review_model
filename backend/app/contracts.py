"""Backend access to contracts/v1 (D22): validation, agent-schema bundling, route roles,
state machines and MongoDB validators derived from the same schemas.

The bundling algorithm matches scripts/contract_tools.py; a test keeps them identical.
"""

from __future__ import annotations

import copy
import json
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker
from referencing import Registry
from referencing.jsonschema import DRAFT202012

from app.config import get_settings
from app.db import iso

TIMESTAMP_REF = "common.schema.json#/$defs/Timestamp"
BSON_TYPES: dict[str, list[str]] = {
    "string": ["string"],
    "integer": ["int", "long"],
    "number": ["double", "int", "long", "decimal"],
    "boolean": ["bool"],
    "null": ["null"],
    "object": ["object"],
    "array": ["array"],
}
MONGO_KEYWORDS = {
    "enum",
    "required",
    "minLength",
    "maxLength",
    "pattern",
    "minimum",
    "maximum",
    "minItems",
    "maxItems",
    "uniqueItems",
    "description",
    "title",
    "minProperties",
}


class ContractStore:
    def __init__(self, directory: Path) -> None:
        self.dir = directory
        self.schemas = {
            p.name: json.loads(p.read_text(encoding="utf-8")) for p in sorted(directory.glob("*.schema.json"))
        }
        resources = []
        for name, schema in self.schemas.items():
            contents = dict(schema)
            contents["$id"] = self._uri(name)
            resources.append((contents["$id"], DRAFT202012.create_resource(contents)))
        self.registry: Registry = Registry().with_resources(resources)
        self.routes = json.loads((directory / "routes.json").read_text(encoding="utf-8"))
        self.machines = json.loads((directory / "state_machines.json").read_text(encoding="utf-8"))["machines"]
        self.content_rules = json.loads((directory / "content_rules.json").read_text(encoding="utf-8"))
        self._validators: dict[str, Draft202012Validator] = {}

    def _uri(self, name: str) -> str:
        return (self.dir / name).resolve().as_uri()

    def resolve(self, ref: str) -> Any:
        file_name, _, pointer = ref.partition("#")
        node: Any = self.schemas[file_name]
        for part in [p for p in pointer.split("/") if p]:
            node = node[part]
        return node

    def errors(self, instance: Any, ref: str) -> list[str]:
        if ref not in self._validators:
            file_name, _, pointer = ref.partition("#")
            self._validators[ref] = Draft202012Validator(
                {"$ref": f"{self._uri(file_name)}#{pointer}"}, registry=self.registry, format_checker=FormatChecker()
            )
        found = sorted(self._validators[ref].iter_errors(instance), key=lambda e: list(e.absolute_path))
        return [f"{'/'.join(str(p) for p in e.absolute_path) or '<root>'}: {e.message}" for e in found]

    def bundle(self, ref: str) -> dict[str, Any]:
        """Self-contained schema with external refs inlined under local $defs (Claude structured outputs)."""
        defs: dict[str, Any] = {}

        def rewrite(node: Any, current_file: str) -> Any:
            if isinstance(node, list):
                return [rewrite(item, current_file) for item in node]
            if not isinstance(node, dict):
                return node
            out: dict[str, Any] = {}
            for key, value in node.items():
                if key == "$ref":
                    target_file, _, pointer = value.partition("#")
                    target_file = target_file or current_file
                    name = f"{target_file.split('.')[0]}__{pointer.rsplit('/', 1)[-1]}"
                    if name not in defs:
                        defs[name] = None
                        defs[name] = rewrite(copy.deepcopy(self.resolve(f"{target_file}#{pointer}")), target_file)
                    elif defs[name] is None:
                        raise ValueError(f"recursive schema through {name}")
                    out["$ref"] = f"#/$defs/{name}"
                elif key == "$defs":
                    continue
                else:
                    out[key] = rewrite(value, current_file)
            return out

        file_name = ref.partition("#")[0]
        root = rewrite(copy.deepcopy(self.resolve(ref)), file_name)
        if defs:
            root["$defs"] = dict(sorted(defs.items()))
        return root

    # --- Routes and state machines ---------------------------------------------------

    def route(self, operation_id: str) -> dict[str, Any]:
        for route in self.routes["routes"]:
            if route["operation_id"] == operation_id:
                return route
        raise KeyError(f"operation {operation_id} is not in contracts/v1/routes.json")

    def roles_for(self, operation_id: str) -> list[str]:
        route = self.route(operation_id)
        return list(self.routes["all_roles"]) if route["roles"] == "all" else list(route["roles"])

    def transition_allowed(self, machine: str, from_state: str | None, to_state: str, actor: str) -> bool:
        spec = self.machines[machine]
        if from_state is None:
            return to_state in spec["initial"]
        return any(
            t["from"] == from_state and t["to"] == to_state and actor in t["actors"] for t in spec["transitions"]
        )

    # --- MongoDB validators -----------------------------------------------------------

    def mongo_validator(
        self, ref: str, *, id_field: str | None = "id", extra: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """$jsonSchema for a collection: timestamps become BSON dates, conditional rules stay in code."""
        file_name = ref.partition("#")[0]
        schema = self._to_mongo(self.resolve(ref), file_name, ())
        properties = schema.setdefault("properties", {})
        if id_field:
            properties["_id"] = properties.pop(id_field)
            schema["required"] = ["_id" if r == id_field else r for r in schema.get("required", [])]
        for name, spec in (extra or {}).items():
            properties[name] = spec
        return {"$jsonSchema": schema}

    def _to_mongo(self, node: Any, current_file: str, stack: tuple[str, ...]) -> dict[str, Any]:
        if not isinstance(node, dict):
            return {}
        if "$ref" in node:
            target_file, _, pointer = node["$ref"].partition("#")
            target = f"{target_file or current_file}#{pointer}"
            if target == TIMESTAMP_REF:
                return {"bsonType": "date"}
            if target in stack:
                return {}
            return self._to_mongo(self.resolve(target), target_file or current_file, (*stack, target))
        out: dict[str, Any] = {}
        for key, value in node.items():
            if key == "type":
                types = value if isinstance(value, list) else [value]
                mapped: list[str] = []
                for t in types:
                    mapped.extend(BSON_TYPES[t])
                out["bsonType"] = mapped[0] if len(mapped) == 1 else mapped
            elif key == "properties":
                out["properties"] = {k: self._to_mongo(v, current_file, stack) for k, v in value.items()}
            elif key in ("items", "not"):
                out[key] = self._to_mongo(value, current_file, stack)
            elif key == "additionalProperties":
                out[key] = value if isinstance(value, bool) else self._to_mongo(value, current_file, stack)
            elif key in ("anyOf", "allOf", "oneOf"):
                converted = [self._to_mongo(v, current_file, stack) for v in value]
                converted = [c for c in converted if c]
                if converted:
                    out[key] = converted
            elif key == "const":
                out["enum"] = [value]
            elif key in MONGO_KEYWORDS:
                out[key] = value
        return out


@lru_cache(maxsize=1)
def get_contracts() -> ContractStore:
    return ContractStore(get_settings().contracts_dir / "v1")


def to_view(doc: dict[str, Any] | None, *, id_field: str | None = "id") -> dict[str, Any] | None:
    """MongoDB document to contract JSON: _id becomes id_field, datetimes become RFC 3339 strings."""
    if doc is None:
        return None

    def convert(value: Any) -> Any:
        if isinstance(value, datetime):
            return iso(value)
        if isinstance(value, dict):
            return {k: convert(v) for k, v in value.items()}
        if isinstance(value, list):
            return [convert(v) for v in value]
        return value

    out = {k: convert(v) for k, v in doc.items() if k != "_id"}
    if id_field:
        out = {id_field: doc["_id"], **out}
    return out
