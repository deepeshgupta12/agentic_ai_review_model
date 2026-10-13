"""Contract tooling for contracts/v1 (Step 02).

Schema loading and validation, canonical hashing (D23), text-anchor conversion
(D24), agent-schema bundling for Claude structured outputs, reference rules for
approval and public reads, and consistency checks for state machines, journeys
and the API route table. Used by scripts/check_contracts.py,
scripts/build_fixtures.py and the tests; Step 03 ports the rules to the backend
with the same fixtures.
"""
from __future__ import annotations

import copy
import hashlib
import json
import re
import unicodedata
from pathlib import Path
from typing import Any, Iterable

import rfc8785
from jsonschema import Draft202012Validator, FormatChecker
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012

ROOT = Path(__file__).resolve().parent.parent
CONTRACTS = ROOT / "contracts" / "v1"
FIXTURES = CONTRACTS / "fixtures"
SAFE_INTEGER = 2**53 - 1
SYSTEM_ACTORS = {"system", "public"}


# --- Loading and validation ----------------------------------------------------


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def schema_files() -> dict[str, dict[str, Any]]:
    return {path.name: load_json(path) for path in sorted(CONTRACTS.glob("*.schema.json"))}


def _file_uri(name: str) -> str:
    return (CONTRACTS / name).resolve().as_uri()


def build_registry(schemas: dict[str, dict[str, Any]] | None = None) -> Registry:
    schemas = schemas if schemas is not None else schema_files()
    resources = []
    for name, schema in schemas.items():
        contents = dict(schema)
        contents["$id"] = _file_uri(name)
        resources.append((contents["$id"], Resource(contents=contents, specification=DRAFT202012)))
    return Registry().with_resources(resources)


class Contracts:
    """All schemas of contracts/v1 with a shared registry."""

    def __init__(self) -> None:
        self.schemas = schema_files()
        self.registry = build_registry(self.schemas)
        self._validators: dict[str, Draft202012Validator] = {}

    def validator(self, ref: str) -> Draft202012Validator:
        """ref is 'file.schema.json#/$defs/Name' (relative to contracts/v1)."""
        if ref not in self._validators:
            file_name, _, pointer = ref.partition("#")
            if file_name not in self.schemas:
                raise KeyError(f"unknown schema file in {ref}")
            schema = {"$ref": f"{_file_uri(file_name)}#{pointer}"}
            self._validators[ref] = Draft202012Validator(schema, registry=self.registry, format_checker=FormatChecker())
        return self._validators[ref]

    def errors(self, instance: Any, ref: str) -> list[str]:
        found = sorted(self.validator(ref).iter_errors(instance), key=lambda e: list(e.absolute_path))
        return [f"{'/'.join(str(p) for p in e.absolute_path) or '<root>'}: {e.message}" for e in _leaf_errors(found)]

    def resolve(self, ref: str) -> Any:
        file_name, _, pointer = ref.partition("#")
        node: Any = self.schemas[file_name]
        for part in [p for p in pointer.split("/") if p]:
            node = node[part.replace("~1", "/").replace("~0", "~")]
        return node

    def enum(self, ref: str) -> list[Any]:
        node = self.resolve(ref)
        if "enum" not in node:
            raise KeyError(f"{ref} is not an enum")
        return list(node["enum"])


def _leaf_errors(errors: Iterable[Any]) -> list[Any]:
    """Expand anyOf/oneOf/allOf failures to their most specific causes, for readable messages."""
    leaves = []
    for error in errors:
        if error.context:
            leaves.extend(_leaf_errors(error.context))
        else:
            leaves.append(error)
    return leaves or list(errors)


def check_schema_files(contracts: Contracts) -> list[str]:
    """Every file is valid Draft 2020-12 and every $ref resolves."""
    problems: list[str] = []
    for name, schema in contracts.schemas.items():
        try:
            Draft202012Validator.check_schema(schema)
        except Exception as exc:  # noqa: BLE001 - report any metaschema failure
            problems.append(f"{name}: not a valid Draft 2020-12 schema: {exc}")
        for ref in _refs(schema):
            target = ref if "#" in ref and not ref.startswith("#") else ref
            absolute = f"{name}{ref}" if ref.startswith("#") else target
            try:
                contracts.resolve(absolute)
            except (KeyError, IndexError, TypeError):
                problems.append(f"{name}: $ref {ref} does not resolve")
    return problems


def _refs(node: Any) -> Iterable[str]:
    if isinstance(node, dict):
        for key, value in node.items():
            if key == "$ref" and isinstance(value, str):
                yield value
            else:
                yield from _refs(value)
    elif isinstance(node, list):
        for item in node:
            yield from _refs(item)


# --- Canonical hashing (D23) ---------------------------------------------------


class CanonicalError(ValueError):
    pass


def _check_canonicalisable(value: Any, path: str = "$") -> None:
    if value is None or isinstance(value, bool):
        return
    if isinstance(value, int):
        if abs(value) > SAFE_INTEGER:
            raise CanonicalError(f"{path}: integer outside the safe range")
        return
    if isinstance(value, float):
        raise CanonicalError(f"{path}: non-integer numbers are not allowed in hashed content")
    if isinstance(value, str):
        if unicodedata.normalize("NFC", value) != value:
            raise CanonicalError(f"{path}: text is not in Unicode NFC form")
        return
    if isinstance(value, list):
        for index, item in enumerate(value):
            _check_canonicalisable(item, f"{path}[{index}]")
        return
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                raise CanonicalError(f"{path}: object keys must be strings")
            if unicodedata.normalize("NFC", key) != key:
                raise CanonicalError(f"{path}: key {key!r} is not in Unicode NFC form")
            _check_canonicalisable(item, f"{path}.{key}")
        return
    raise CanonicalError(f"{path}: unsupported type {type(value).__name__}")


def canonical_bytes(value: Any) -> bytes:
    """RFC 8785 (JCS) bytes, after rejecting floats, unsafe integers and non-NFC text."""
    _check_canonicalisable(value)
    return rfc8785.dumps(value)


def content_hash(value: Any) -> str:
    return "sha256:" + hashlib.sha256(canonical_bytes(value)).hexdigest()


# --- Text anchors (D24) ------------------------------------------------------------


def utf16_offset(text: str, codepoint_index: int) -> int:
    """UTF-16 code-unit offset of a code-point index (astral characters count twice)."""
    return sum(2 if ord(ch) > 0xFFFF else 1 for ch in text[:codepoint_index])


def codepoint_offset(text: str, utf16_index: int) -> int:
    units = 0
    for index, ch in enumerate(text):
        if units == utf16_index:
            return index
        units += 2 if ord(ch) > 0xFFFF else 1
        if units > utf16_index:
            raise ValueError("UTF-16 offset falls inside a surrogate pair")
    if units == utf16_index:
        return len(text)
    raise ValueError("UTF-16 offset beyond the end of the text")


# --- Agent schemas for Claude structured outputs --------------------------------------

CLAUDE_ALLOWED_KEYS = {
    "type",
    "properties",
    "required",
    "additionalProperties",
    "items",
    "enum",
    "const",
    "anyOf",
    "allOf",
    "$ref",
    "$defs",
    "description",
    "title",
    "format",
}
CLAUDE_FORMATS = {"date-time", "time", "date", "duration", "email", "hostname", "uri", "ipv4", "ipv6", "uuid"}


def bundle_schema(contracts: Contracts, ref: str) -> dict[str, Any]:
    """Self-contained copy of a schema with every external $ref inlined under local $defs."""
    defs: dict[str, Any] = {}

    def local_name(file_name: str, pointer: str) -> str:
        return f"{file_name.split('.')[0]}__{pointer.rsplit('/', 1)[-1]}"

    def rewrite(node: Any, current_file: str) -> Any:
        if isinstance(node, list):
            return [rewrite(item, current_file) for item in node]
        if not isinstance(node, dict):
            return node
        out = {}
        for key, value in node.items():
            if key == "$ref":
                target_file, _, pointer = value.partition("#")
                target_file = target_file or current_file
                name = local_name(target_file, pointer)
                if name not in defs:
                    defs[name] = None  # marks "in progress" to detect recursion
                    defs[name] = rewrite(copy.deepcopy(contracts.resolve(f"{target_file}#{pointer}")), target_file)
                elif defs[name] is None:
                    raise ValueError(f"recursive schema through {name}")
                out["$ref"] = f"#/$defs/{name}"
            elif key == "$defs":
                continue
            else:
                out[key] = rewrite(value, current_file)
        return out

    file_name, _, pointer = ref.partition("#")
    root = rewrite(copy.deepcopy(contracts.resolve(ref)), file_name)
    if defs:
        root["$defs"] = dict(sorted(defs.items()))
    return root


def claude_subset_violations(schema: dict[str, Any]) -> list[str]:
    """Rules from the Claude structured-output docs: closed objects, all properties required, no constraints."""
    problems: list[str] = []

    def walk(node: Any, path: str) -> None:
        if not isinstance(node, dict):
            problems.append(f"{path}: schema must be an object")
            return
        for key in sorted(set(node) - CLAUDE_ALLOWED_KEYS):
            problems.append(f"{path}: keyword '{key}' is not supported")
        if "format" in node and node["format"] not in CLAUDE_FORMATS:
            problems.append(f"{path}: format '{node['format']}' is not supported")
        if node.get("type") == "object":
            properties = node.get("properties", {})
            if node.get("additionalProperties") is not False:
                problems.append(f"{path}: objects need additionalProperties: false")
            if sorted(node.get("required", [])) != sorted(properties):
                problems.append(f"{path}: every property must be required (use null for optional values)")
            for name, sub in properties.items():
                walk(sub, f"{path}.{name}")
        if "items" in node:
            walk(node["items"], f"{path}[]")
        for key in ("anyOf", "allOf"):
            for index, sub in enumerate(node.get(key, [])):
                walk(sub, f"{path}.{key}[{index}]")
        for name, sub in node.get("$defs", {}).items():
            walk(sub, f"$defs.{name}")

    walk(schema, "$")
    return problems


# --- Reference rules (executable spec for Steps 10-11) ---------------------------------


def approval_authorises(decision: dict[str, Any], revision: dict[str, Any], state: dict[str, Any]) -> tuple[bool, list[str]]:
    """Does this final approval authorise publishing this exact revision now? (docs/05 steps 2-4)"""
    reasons: list[str] = []
    target = decision.get("target", {})
    binding = decision.get("binding") or {}
    if target.get("type") != "content_revision" or decision.get("action") != "approve":
        reasons.append("not a final approval")
    if decision.get("actor", {}).get("kind") != "user":
        reasons.append("approval not made by a person")
    if target.get("id") != revision["id"] or target.get("revision") != revision["revision"]:
        reasons.append("approval names a different revision")
    recomputed_payload = content_hash(revision["payload"])
    recomputed_manifest = content_hash(revision["manifest"])
    if recomputed_payload != revision["payload_sha256"]:
        reasons.append("stored payload hash does not match the payload")
    if recomputed_manifest != revision["manifest_sha256"]:
        reasons.append("stored manifest hash does not match the manifest")
    if binding.get("payload_sha256") != recomputed_payload:
        reasons.append("approved payload hash differs from this payload")
    if binding.get("manifest_sha256") != recomputed_manifest:
        reasons.append("approved manifest hash differs from this manifest")
    if binding.get("project_id") != revision["project_id"] or binding.get("locale") != revision["locale"]:
        reasons.append("approval is for another project or locale")
    if binding.get("eligibility_epoch") != state["eligibility_epoch"]:
        reasons.append("evidence eligibility changed since approval")
    if state.get("pending_invalidation"):
        reasons.append("an invalidation is pending")
    if revision.get("lifecycle") != "approved":
        reasons.append(f"revision lifecycle is {revision.get('lifecycle')}, not approved")
    return (not reasons, reasons)


def public_revision(state: dict[str, Any], revisions: list[dict[str, Any]]) -> dict[str, Any] | None:
    """What the public page may show: the active pointer when serving is active; never the newest draft."""
    if state.get("serving_state") != "active" or not state.get("active"):
        return None
    active = state["active"]
    for revision in revisions:
        if revision["id"] == active["revision_id"] and revision["revision"] == active["revision"]:
            if revision["payload_sha256"] != active["payload_sha256"] or revision.get("lifecycle") != "approved":
                return None
            return revision
    return None


def manifest_problems(revision: dict[str, Any]) -> list[str]:
    """Manifest arrays sorted and unique; every payload reference listed; payload names the same project."""
    problems: list[str] = []
    manifest, payload = revision["manifest"], revision["payload"]
    for key in ("findings", "claims", "evidence", "sources"):
        pairs = [(item["id"], item["revision"]) for item in manifest[key]]
        if pairs != sorted(set(pairs)):
            problems.append(f"manifest.{key} must be sorted by (id, revision) and unique")
    for key in ("links",):
        if manifest[key] != sorted(set(manifest[key])):
            problems.append(f"manifest.{key} must be sorted and unique")
    policies = [(p["family"], p["policy_version"]) for p in manifest["policies"]]
    if policies != sorted(set(policies)):
        problems.append("manifest.policies must be sorted by (family, policy_version) and unique")
    listed_findings = {(f["id"], f["revision"]) for f in manifest["findings"]}
    listed_claims = {(c["id"], c["revision"]) for c in manifest["claims"]}
    overview = [payload["overview"]] if payload["overview"] is not None else []  # null on a reviews-only page (D64)
    blocks = [*overview, *payload["advantages"], *payload["considerations"], *payload["questions"]]
    for block in blocks:
        for ref in block["support"]["findings"]:
            if (ref["id"], ref["revision"]) not in listed_findings:
                problems.append(f"payload cites finding {ref['id']} r{ref['revision']} missing from the manifest")
        for ref in block["support"]["claims"]:
            if (ref["id"], ref["revision"]) not in listed_claims:
                problems.append(f"payload cites claim {ref['id']} r{ref['revision']} missing from the manifest")
    reviews = [(r["id"], r["revision"]) for r in manifest["reviews"]]
    if reviews != sorted(set(reviews)):
        problems.append("manifest.reviews must be sorted by (id, revision) and unique")
    listed_evidence = {(e["id"], e["revision"]) for e in manifest["evidence"]}
    listed_sources = {(s["id"], s["revision"]) for s in manifest["sources"]}
    forbidden = set(content_rules()["review_text"]["forbidden_characters"])
    for review in payload["reviews"]:
        support_ = review["support"]
        if (support_["review"]["id"], support_["review"]["revision"]) not in set(reviews):
            problems.append(f"payload shows review {support_['review']['id']} missing from the manifest")
        if (support_["source"]["id"], support_["source"]["revision"]) not in listed_sources:
            problems.append(f"review {support_['review']['id']} cites a source missing from the manifest")
        for ref in support_["evidence"]:
            if (ref["id"], ref["revision"]) not in listed_evidence:
                problems.append(f"review {support_['review']['id']} cites evidence missing from the manifest")
        if forbidden & set(review["text"]):
            problems.append(f"review {support_['review']['id']} text contains a dash or hyphen")
    if payload["project"]["id"] != revision["project_id"]:
        problems.append("payload.project.id differs from project_id")
    if json_ld_has_ratings(payload["json_ld"]):
        problems.append("json_ld contains a rating or review entity")
    return problems


# --- Construction status and source reviews (D27, D28) -----------------------------------


def content_rules() -> dict[str, Any]:
    return load_json(CONTRACTS / "content_rules.json")


def status_from_export_label(label: str, rules: dict[str, Any] | None = None) -> str | None:
    """Map an export label such as 'Partially Ready To Move' to a ConstructionStatus, or None if unknown."""
    rules = rules or content_rules()
    return rules["export_labels"].get(" ".join(label.casefold().split()))


def applicable_status(records: list[dict[str, Any]], phase_rera_id: str | None = None, on_date: str | None = None) -> str | None:
    """Latest status on or before on_date: the phase's own record if there is one, else the project's."""

    def known_by(record: dict[str, Any]) -> bool:
        return on_date is None or record["as_of"] <= on_date

    if phase_rera_id:
        phase = [
            r for r in records
            if r["applies_to"]["kind"] == "phase" and r["applies_to"]["rera_id"] == phase_rera_id and known_by(r)
        ]
        if phase:
            return max(phase, key=lambda r: r["as_of"])["status"]
    project = [r for r in records if r["applies_to"]["kind"] == "project" and known_by(r)]
    return max(project, key=lambda r: r["as_of"])["status"] if project else None


def consistency_flags(
    perspective: str,
    records: list[dict[str, Any]],
    phase_rera_id: str | None = None,
    on_date: str | None = None,
    rules: dict[str, Any] | None = None,
) -> list[str]:
    """Flags for a claim or review: living experience where nobody can live yet, or where status cannot tell."""
    rules = rules or content_rules()
    if perspective not in rules["occupancy_perspectives"]:
        return []
    status = applicable_status(records, phase_rera_id, on_date)
    if status is None:
        return ["status_unknown"]
    possible = rules["occupancy_possible"][status]
    if possible == "no":
        return ["occupancy_before_possession"]
    if possible == "phase_dependent":
        return ["status_unknown"]
    return []


def wording_issues(text: str, status: str | None, rules: dict[str, Any] | None = None) -> dict[str, list[str]]:
    """Occupancy wording in the client's own page text: blocking before possession, advice when partially ready."""
    rules = rules or content_rules()
    found = [
        term
        for term in rules["wording"]["occupancy_terms"]
        if re.search(rf"(?<!\w){re.escape(term)}(?!\w)", text, flags=re.IGNORECASE)
    ]
    possible = rules["occupancy_possible"].get(status) if status else None
    if possible == "no":
        return {"blocking": found, "advice": []}
    if possible in ("phase_dependent", None):
        return {"blocking": [], "advice": found}
    return {"blocking": [], "advice": []}


_WORD = re.compile(r"[^\W_]+")
_SENTENCE_END = re.compile(r"(?<=[.!?।])\s+")


def _words(text: str) -> list[str]:
    return [w.casefold() for w in _WORD.findall(unicodedata.normalize("NFC", text))]


def _sentences(text: str) -> list[list[str]]:
    return [_words(s) for s in _SENTENCE_END.split(text.strip()) if _words(s)]


def rendering_problems(original: str, text: str, rendering: str, rules: dict[str, Any] | None = None) -> list[str]:
    """Is the displayed review still the author's own words? Translations are left to the moderator and A09."""
    rules = rules or content_rules()
    problems: list[str] = []
    if set(rules["review_text"]["forbidden_characters"]) & set(text):
        problems.append("displayed text contains a dash or hyphen")
    if rendering == "verbatim":
        if text != original:
            problems.append("verbatim text differs from the original")
    elif rendering == "punctuation_normalised":
        if _words(text) != _words(original):
            problems.append("words differ from the original; only punctuation may change")
    elif rendering == "shortened":
        remaining = iter(_sentences(original))
        if not all(any(kept == sentence for sentence in remaining) for kept in _sentences(text)):
            problems.append("a sentence is not in the original, or sentences were reordered or edited")
    elif rendering != "translated":
        problems.append(f"unknown rendering {rendering}")
    return problems


def rendering_check(original: str, text: str, rendering: str) -> str:
    """Value shown to moderators (ReviewExcerptView.rendering_check)."""
    if rendering_problems(original, text, rendering):
        return "mismatch"
    return "needs_moderator" if rendering == "translated" else "matches_original"


def json_ld_has_ratings(node: Any) -> bool:
    if isinstance(node, dict):
        if any(key in ("aggregateRating", "review", "reviewRating") for key in node):
            return True
        if node.get("@type") in ("Review", "AggregateRating", "Rating"):
            return True
        return any(json_ld_has_ratings(value) for value in node.values())
    if isinstance(node, list):
        return any(json_ld_has_ratings(item) for item in node)
    return False


# --- State machines, journeys and routes ----------------------------------------------


def check_state_machines(contracts: Contracts, machines_doc: dict[str, Any], roles: list[str]) -> list[str]:
    problems: list[str] = []
    valid_actors = set(roles) | SYSTEM_ACTORS
    covered_enums = set()
    for name, machine in machines_doc["machines"].items():
        label = f"machine '{name}'"
        states = set(contracts.enum(machine["enum"]))
        covered_enums.add(machine["enum"])
        initial, terminal = set(machine["initial"]), set(machine["terminal"])
        if not initial <= states or not terminal <= states:
            problems.append(f"{label}: initial/terminal states must come from {machine['enum']}")
        outgoing: dict[str, set[str]] = {state: set() for state in states}
        seen_pairs = set()
        for t in machine["transitions"]:
            if t["from"] not in states or t["to"] not in states:
                problems.append(f"{label}: transition {t['from']} -> {t['to']} uses a state outside the enum")
                continue
            if (t["from"], t["to"]) in seen_pairs:
                problems.append(f"{label}: duplicate transition {t['from']} -> {t['to']}")
            seen_pairs.add((t["from"], t["to"]))
            if t["from"] == t["to"]:
                problems.append(f"{label}: self-transition {t['from']}")
            if not t.get("actors") or not set(t["actors"]) <= valid_actors:
                problems.append(f"{label}: transition {t['from']} -> {t['to']} has invalid actors {t.get('actors')}")
            if not t.get("trigger"):
                problems.append(f"{label}: transition {t['from']} -> {t['to']} has no trigger")
            outgoing[t["from"]].add(t["to"])
        for state in terminal:
            if outgoing.get(state):
                problems.append(f"{label}: terminal state '{state}' has outgoing transitions")
        for state in states - terminal:
            if not outgoing.get(state):
                problems.append(f"{label}: state '{state}' has no way out but is not terminal")
        reachable, frontier = set(initial), list(initial)
        while frontier:
            for nxt in outgoing.get(frontier.pop(), ()):
                if nxt not in reachable:
                    reachable.add(nxt)
                    frontier.append(nxt)
        for state in sorted(states - reachable):
            problems.append(f"{label}: state '{state}' is unreachable from {sorted(initial)}")
        record = machine.get("record", "")
        if record.endswith("schema.json") or ".schema.json#" in record:
            field_schema = contracts.resolve(record).get("properties", {}).get(machine["field"])
            refs = set(_refs(field_schema)) if field_schema is not None else set()
            if machine["enum"] not in refs:
                problems.append(f"{label}: {record}.{machine['field']} does not reference {machine['enum']}")
    for name, classification in machines_doc.get("classifications", {}).items():
        covered_enums.add(classification["enum"])
        values = set(contracts.enum(classification["enum"]))
        if set(classification["meaning"]) != values:
            problems.append(f"classification '{name}': meanings must cover exactly {sorted(values)}")
    for def_name in contracts.schemas["common.schema.json"]["$defs"]:
        ref = f"common.schema.json#/$defs/{def_name}"
        if re.search(r"(Status|Stage|Lifecycle|State)$", def_name) and ref not in covered_enums:
            problems.append(f"{ref}: status vocabulary has no state machine or classification")
    return problems


def duplicate_status_enums(contracts: Contracts) -> list[str]:
    """No schema outside common redefines a status vocabulary inline."""
    common = contracts.schemas["common.schema.json"]["$defs"]
    vocab = {
        frozenset(node["enum"]): name
        for name, node in common.items()
        if "enum" in node and re.search(r"(Status|Stage|Lifecycle|State)$", name)
    }
    problems = []
    for file_name, schema in contracts.schemas.items():
        if file_name == "common.schema.json":
            continue
        for path, enum in _inline_enums(schema, "$"):
            if frozenset(enum) in vocab:
                problems.append(f"{file_name} {path}: redefines {vocab[frozenset(enum)]} inline; use a $ref")
    return problems


def _inline_enums(node: Any, path: str) -> Iterable[tuple[str, list[Any]]]:
    if isinstance(node, dict):
        if isinstance(node.get("enum"), list):
            yield path, node["enum"]
        for key, value in node.items():
            yield from _inline_enums(value, f"{path}.{key}")
    elif isinstance(node, list):
        for index, item in enumerate(node):
            yield from _inline_enums(item, f"{path}[{index}]")


def route_roles(route: dict[str, Any], all_roles: list[str]) -> list[str]:
    return list(all_roles) if route["roles"] == "all" else list(route["roles"])


def check_routes(contracts: Contracts, routes_doc: dict[str, Any]) -> list[str]:
    problems: list[str] = []
    roles = set(contracts.enum("common.schema.json#/$defs/Role"))
    if set(routes_doc["all_roles"]) != roles:
        problems.append("routes.json all_roles must equal the Role enum")
    seen_ops, seen_paths = set(), set()
    for route in routes_doc["routes"]:
        op = route["operation_id"]
        if op in seen_ops:
            problems.append(f"route {op}: duplicate operation_id")
        seen_ops.add(op)
        key = (route["method"], route["path"])
        if key in seen_paths:
            problems.append(f"route {op}: duplicate {route['method']} {route['path']}")
        seen_paths.add(key)
        allowed = route_roles(route, routes_doc["all_roles"])
        if route["access"] == "session" and (not allowed or not set(allowed) <= roles):
            problems.append(f"route {op}: session routes need roles from the Role enum")
        if route["access"] != "session" and allowed:
            problems.append(f"route {op}: {route['access']} routes must not list roles")
        if route["access"] == "public" and not route["path"].startswith(("/v1/public/", "/v1/auth/login")):
            problems.append(f"route {op}: public routes live under /v1/public/")
        for ref in [route.get("request"), *route["responses"].values()]:
            if ref and not ref.startswith("inline:"):
                try:
                    contracts.resolve(ref)
                except (KeyError, IndexError):
                    problems.append(f"route {op}: {ref} does not resolve")
        for name in re.findall(r"\{([a-z_]+)\}", route["path"]):
            if name not in routes_doc["path_parameters"]:
                problems.append(f"route {op}: path parameter {name} is not defined")
        for name in route.get("query", []):
            if name not in routes_doc["query_parameters"]:
                problems.append(f"route {op}: query parameter {name} is not defined")
        if route["method"] != "GET" and route["access"] == "session" and route["method"] == "POST" and op.startswith(("list", "get")):
            problems.append(f"route {op}: read operations must use GET")
    return problems


def check_journeys(journeys_doc: dict[str, Any], machines_doc: dict[str, Any], routes_doc: dict[str, Any]) -> list[str]:
    problems: list[str] = []
    routes = {route["operation_id"]: route for route in routes_doc["routes"]}
    machines = machines_doc["machines"]
    covered: set[str] = set()
    for journey in journeys_doc["journeys"]:
        jid = journey["id"]
        covered |= set(journey["covers"])
        position: dict[tuple[str, str], str] = {}
        for number, step in enumerate(journey["steps"], start=1):
            label = f"{jid} step {number}"
            actor, op = step["actor"], step.get("operation")
            if op is None:
                if actor != "system":
                    problems.append(f"{label}: only system steps may omit the operation")
            elif op not in routes:
                problems.append(f"{label}: unknown operation {op}")
            else:
                route = routes[op]
                if route["access"] == "public":
                    if actor != "public":
                        problems.append(f"{label}: {op} is a public operation; actor must be 'public'")
                elif route["access"] == "session" and actor not in route_roles(route, routes_doc["all_roles"]):
                    problems.append(f"{label}: role '{actor}' may not call {op}")
            for t in step.get("transitions", []):
                machine = machines.get(t["machine"])
                if machine is None:
                    problems.append(f"{label}: unknown machine {t['machine']}")
                    continue
                key = (t["machine"], t.get("instance", "default"))
                if t["from"] is None:
                    if t["to"] not in machine["initial"]:
                        problems.append(f"{label}: {t['machine']} records start in {machine['initial']}, not {t['to']}")
                    if key in position:
                        problems.append(f"{label}: {key} created twice")
                else:
                    match = [x for x in machine["transitions"] if x["from"] == t["from"] and x["to"] == t["to"]]
                    if not match:
                        problems.append(f"{label}: {t['machine']} has no transition {t['from']} -> {t['to']}")
                    elif actor not in match[0]["actors"]:
                        problems.append(f"{label}: {actor} may not move {t['machine']} {t['from']} -> {t['to']}")
                    if key in position and position[key] != t["from"]:
                        problems.append(f"{label}: {key} is in '{position[key]}', not '{t['from']}'")
                position[key] = t["to"]
    for tag in journeys_doc["required_coverage"]:
        if tag not in covered:
            problems.append(f"journeys: no journey covers '{tag}'")
    return problems


# --- Rendering ------------------------------------------------------------------------------


def render_journeys_doc(journeys_doc: dict[str, Any], machines_doc: dict[str, Any], routes_doc: dict[str, Any]) -> str:
    routes = {route["operation_id"]: route for route in routes_doc["routes"]}
    out = [
        "# Journeys and state machines",
        "",
        "Generated from [contracts/v1/journeys.json](../contracts/v1/journeys.json) and "
        "[contracts/v1/state_machines.json](../contracts/v1/state_machines.json) by "
        "`python3 scripts/check_contracts.py --render`. Do not edit by hand; `scripts/check_contracts.py` fails when this file is stale.",
        "",
        "## Journeys",
        "",
    ]
    for journey in journeys_doc["journeys"]:
        out += [f"### {journey['id']}: {journey['title']}", "", f"Covers: {', '.join(journey['covers'])}.", ""]
        out += ["| # | Actor | API call | What happens | State changes |", "|---|---|---|---|---|"]
        for number, step in enumerate(journey["steps"], start=1):
            op = step.get("operation")
            call = f"`{routes[op]['method']} {routes[op]['path']}` ({op})" if op in routes else "—"
            changes = "; ".join(
                f"{t['machine']}[{t.get('instance', '')}]: {t['from'] or 'new'} → {t['to']}" for t in step.get("transitions", [])
            ) or "—"
            out.append(f"| {number} | {step['actor']} | {call} | {step['does']} | {changes} |")
        out.append("")
    out += ["## State machines", ""]
    for name, machine in machines_doc["machines"].items():
        enum_name = machine["enum"].rsplit("/", 1)[-1]
        out += [
            f"### {name}",
            "",
            f"States (`{enum_name}`), field `{machine['field']}` of `{machine['record'].rsplit('/', 1)[-1]}`. "
            f"Starts in {', '.join(f'`{s}`' for s in machine['initial'])}; "
            f"ends in {', '.join(f'`{s}`' for s in machine['terminal']) or 'no terminal state'}.",
            "",
            "| From | To | Who | Trigger |",
            "|---|---|---|---|",
        ]
        for t in machine["transitions"]:
            out.append(f"| `{t['from']}` | `{t['to']}` | {', '.join(t['actors'])} | {t['trigger']} |")
        out.append("")
    out += ["## Classifications", ""]
    for name, classification in machines_doc.get("classifications", {}).items():
        out += [f"### {name}", "", "| Value | Meaning |", "|---|---|"]
        out += [f"| `{value}` | {meaning} |" for value, meaning in classification["meaning"].items()]
        out.append("")
    return "\n".join(out).rstrip() + "\n"
