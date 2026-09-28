#!/usr/bin/env python3
"""Generate contracts/v1/openapi.json from contracts/v1/routes.json.

    python3 scripts/build_openapi.py          # write openapi.json
    python3 scripts/build_openapi.py --check  # exit 1 if openapi.json is out of date

Schemas stay in the contract files; OpenAPI components only reference them, so
there is one definition of every shape (D22). Standard library only.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
CONTRACTS = ROOT / "contracts" / "v1"
ROUTES = CONTRACTS / "routes.json"
OPENAPI = CONTRACTS / "openapi.json"

ERROR_DESCRIPTIONS = {
    401: "Not signed in, or the webhook signature is invalid",
    403: "Signed in without a role allowed for this operation",
    404: "Not found (also returned when the caller may not know it exists)",
    409: "Version, idempotency, approval or state conflict; the body names the current version",
    422: "Request failed validation",
    429: "Rate limited",
    503: "A provider or dependency is unavailable",
}
MUTATING = {"POST", "PATCH", "PUT", "DELETE"}


def _schema_name(ref: str) -> str:
    return ref.rsplit("/", 1)[-1]


def _param(name: str, location: str, schema: dict[str, Any], required: bool, description: str | None = None) -> dict[str, Any]:
    param: dict[str, Any] = {"name": name, "in": location, "required": required, "schema": schema}
    if description:
        param["description"] = description
    return param


def build(routes: dict[str, Any]) -> dict[str, Any]:
    all_roles = routes["all_roles"]
    schemas: dict[str, dict[str, str]] = {"ErrorEnvelope": {"$ref": "common.schema.json#/$defs/ErrorEnvelope"}}
    sources: dict[str, str] = {"ErrorEnvelope": "common.schema.json#/$defs/ErrorEnvelope"}

    def component(ref: str) -> dict[str, str]:
        name = _schema_name(ref)
        if name in sources and sources[name] != ref:
            raise ValueError(f"schema name collision: {name} is both {sources[name]} and {ref}")
        sources[name] = ref
        schemas[name] = {"$ref": ref}
        return {"$ref": f"#/components/schemas/{name}"}

    paths: dict[str, dict[str, Any]] = {}
    for route in routes["routes"]:
        method = route["method"].upper()
        roles = all_roles if route["roles"] == "all" else route["roles"]
        op: dict[str, Any] = {
            "operationId": route["operation_id"],
            "summary": route["summary"],
            "tags": [route["tag"]],
            "x-access": route["access"],
            "x-roles": roles,
        }

        if route["access"] == "session":
            op["security"] = [{"sessionCookie": [], "csrfToken": []}] if method in MUTATING else [{"sessionCookie": []}]
        elif route["access"] == "signature":
            op["security"] = [{"webhookSignature": []}]
        else:
            op["security"] = []

        params = [
            _param(name, "path", routes["path_parameters"][name], True)
            for name in re.findall(r"\{([a-z_]+)\}", route["path"])
        ]
        params += [_param(name, "query", routes["query_parameters"][name], False) for name in route.get("query", [])]
        if route.get("idempotent"):
            params.append({"$ref": "#/components/parameters/IdempotencyKey"})
        if route.get("sse"):
            params.append(_param("Last-Event-ID", "header", {"type": "string"}, False, "Resume after this event ID"))
        if params:
            op["parameters"] = params

        request = route.get("request")
        if request == "inline:object":
            op["requestBody"] = {"required": True, "content": {"application/json": {"schema": {"type": "object"}}}}
        elif request:
            op["requestBody"] = {"required": True, "content": {"application/json": {"schema": component(request)}}}

        responses: dict[str, Any] = {}
        for status, ref in route["responses"].items():
            if ref is None:
                responses[status] = {"description": "No content"}
            elif route.get("sse"):
                responses[status] = {"description": "Event stream", "content": {"text/event-stream": {"schema": component(ref)}}}
            else:
                responses[status] = {"description": _schema_name(ref), "content": {"application/json": {"schema": component(ref)}}}
        errors = set(route["errors"])
        if route["access"] == "session":
            errors |= {401, 403}
        for status in sorted(errors):
            responses[str(status)] = {"$ref": f"#/components/responses/Error{status}"}
        op["responses"] = responses

        paths.setdefault(route["path"], {})[method.lower()] = op

    return {
        "openapi": "3.1.0",
        "info": {
            "title": "Agentic Project Intelligence API",
            "version": routes["version"],
            "description": "Generated from contracts/v1/routes.json by scripts/build_openapi.py. Do not edit by hand.",
        },
        "servers": [{"url": "/"}],
        "paths": paths,
        "components": {
            "securitySchemes": {
                "sessionCookie": {"type": "apiKey", "in": "cookie", "name": "sy_session"},
                "csrfToken": {"type": "apiKey", "in": "header", "name": "X-CSRF-Token"},
                "webhookSignature": {"type": "apiKey", "in": "header", "name": "X-Webhook-Signature"},
            },
            "parameters": {
                "IdempotencyKey": _param(
                    "Idempotency-Key",
                    "header",
                    {"type": "string", "minLength": 8, "maxLength": 128},
                    True,
                    "Same key and body returns the original result; same key with a different body returns 409",
                )
            },
            "responses": {
                f"Error{status}": {
                    "description": text,
                    "content": {"application/json": {"schema": {"$ref": "#/components/schemas/ErrorEnvelope"}}},
                }
                for status, text in ERROR_DESCRIPTIONS.items()
            },
            "schemas": dict(sorted(schemas.items())),
        },
    }


def render(document: dict[str, Any]) -> str:
    return json.dumps(document, indent=2, ensure_ascii=False) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true", help="fail if openapi.json is not up to date")
    args = parser.parse_args(argv)

    expected = render(build(json.loads(ROUTES.read_text(encoding="utf-8"))))
    if args.check:
        current = OPENAPI.read_text(encoding="utf-8") if OPENAPI.exists() else ""
        if current != expected:
            print("openapi.json is out of date: run python3 scripts/build_openapi.py")
            return 1
        print("openapi.json is up to date")
        return 0
    OPENAPI.write_text(expected, encoding="utf-8")
    print(f"wrote {OPENAPI.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
