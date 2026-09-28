#!/usr/bin/env python3
"""Step 02 contract checks.

Validates contracts/v1 end to end: schema files, status vocabulary and state
machines, the route table and generated OpenAPI, journeys, agent output schemas
(Claude structured-output subset), fixtures, canonical hashing, text anchors,
approval/public-read rules, seed-data vocabulary, docs, and the JavaScript
cross-check. Exit code 0 only when every section passes.

    .venv/bin/python scripts/check_contracts.py            # report
    .venv/bin/python scripts/check_contracts.py --render   # regenerate docs/10 first
    .venv/bin/python scripts/check_contracts.py --json
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable

sys.path.insert(0, str(Path(__file__).resolve().parent))
import build_fixtures  # noqa: E402
import build_openapi  # noqa: E402
import contract_tools as ct  # noqa: E402

ROOT = ct.ROOT
JOURNEYS_DOC = ROOT / "docs" / "10-journeys-and-states.md"
SCREENS_DOC = ROOT / "docs" / "09-screen-specifications.md"
REQUIRED_FIXTURE_TAGS = ("multi_project_video", "unknown_date", "insufficient_evidence", "withdrawal")
OPERATIONS_WITHOUT_SCREEN = {"receiveWebhook"}


def _docs() -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    return (
        ct.load_json(ct.CONTRACTS / "routes.json"),
        ct.load_json(ct.CONTRACTS / "state_machines.json"),
        ct.load_json(ct.CONTRACTS / "journeys.json"),
    )


def check_vocabulary(c: ct.Contracts) -> list[str]:
    _, machines, _ = _docs()
    return ct.check_state_machines(c, machines, c.enum("common.schema.json#/$defs/Role")) + ct.duplicate_status_enums(c)


def check_api(c: ct.Contracts) -> list[str]:
    routes, _, _ = _docs()
    problems = ct.check_routes(c, routes)
    expected = build_openapi.render(build_openapi.build(routes))
    if build_openapi.OPENAPI.read_text(encoding="utf-8") != expected:
        problems.append("openapi.json is out of date: run python3 scripts/build_openapi.py")
    for name, component in ct.load_json(build_openapi.OPENAPI)["components"]["schemas"].items():
        try:
            c.resolve(component["$ref"])
        except (KeyError, IndexError):
            problems.append(f"openapi component {name}: {component['$ref']} does not resolve")
    return problems


def check_journeys(c: ct.Contracts) -> list[str]:
    routes, machines, journeys = _docs()
    return ct.check_journeys(journeys, machines, routes)


def check_agents(c: ct.Contracts) -> list[str]:
    problems: list[str] = []
    outputs = c.schemas["agents.schema.json"]["x-agent-outputs"]
    for agent in c.enum("common.schema.json#/$defs/AgentId"):
        if agent == "A00_master_coordinator":
            if agent in outputs:
                problems.append("A00 is deterministic and must not have a model output schema")
            continue
        if agent not in outputs:
            problems.append(f"{agent}: no output schema")
            continue
        ref = f"agents.schema.json#/$defs/{outputs[agent]}"
        try:
            bundled = ct.bundle_schema(c, ref)
        except ValueError as exc:
            problems.append(f"{agent}: {exc}")
            continue
        problems += [f"{agent} ({outputs[agent]}): {p}" for p in ct.claude_subset_violations(bundled)]
        if "outcome" not in bundled.get("properties", {}):
            problems.append(f"{agent}: output must report an outcome (valid abstention)")
    return problems


def fixture_cases() -> list[tuple[str, dict[str, Any]]]:
    found = []
    for path in sorted(ct.FIXTURES.glob("*.json")):
        for item in ct.load_json(path).get("cases", []):
            if "schema" in item:
                found.append((path.name, item))
    return found


def check_fixtures(c: ct.Contracts) -> list[str]:
    problems: list[str] = []
    rendered = build_fixtures.render_all()
    for name, text in rendered.items():
        path = ct.FIXTURES / name
        if not path.exists() or path.read_text(encoding="utf-8") != text:
            problems.append(f"fixtures/{name} is stale: run scripts/build_fixtures.py")
    valid_tags: set[str] = set()
    for file_name, item in fixture_cases():
        label = f"{file_name}:{item['name']}"
        errors = c.errors(item["instance"], item["schema"])
        if item["expect"] == "valid":
            if errors:
                problems.append(f"{label}: should be valid but {errors[0]}")
            valid_tags |= set(item["tags"])
        elif not errors:
            problems.append(f"{label}: should be invalid ({item['why']}) but passed")
        elif not any(item["error_contains"] in e for e in errors):
            problems.append(f"{label}: failed for another reason than '{item['error_contains']}': {errors[:2]}")
    for tag in REQUIRED_FIXTURE_TAGS:
        if tag not in valid_tags:
            problems.append(f"no valid fixture covers '{tag}' (Step 02 acceptance)")
    return problems


def check_hashing(c: ct.Contracts) -> list[str]:
    problems: list[str] = []
    vectors = ct.load_json(ct.FIXTURES / "hashing.json")
    for item in vectors["cases"]:
        if ct.canonical_bytes(item["value"]).decode("utf-8") != item["canonical"]:
            problems.append(f"hashing {item['name']}: canonical form differs")
        if ct.content_hash(item["value"]) != item["sha256"]:
            problems.append(f"hashing {item['name']}: sha256 differs")
    for item in vectors["rejects"]:
        try:
            ct.canonical_bytes(item["value"])
            problems.append(f"hashing reject {item['name']}: accepted but must be rejected ({item['reason']})")
        except ct.CanonicalError:
            pass
    for file_name, item in fixture_cases():
        if item["expect"] == "valid" and item["schema"].endswith("/ContentRevision"):
            revision = item["instance"]
            if ct.content_hash(revision["payload"]) != revision["payload_sha256"]:
                problems.append(f"{file_name}:{item['name']}: payload_sha256 does not match the payload")
            if ct.content_hash(revision["manifest"]) != revision["manifest_sha256"]:
                problems.append(f"{file_name}:{item['name']}: manifest_sha256 does not match the manifest")
            problems += [f"{file_name}:{item['name']}: {p}" for p in ct.manifest_problems(revision)]
    return problems


def check_anchors(c: ct.Contracts) -> list[str]:
    problems: list[str] = []
    for item in ct.load_json(ct.FIXTURES / "anchors.json")["cases"]:
        text, start, end = item["text"], item["start"], item["end"]
        if text[start:end] != item["excerpt"]:
            problems.append(f"anchor {item['name']}: code-point slice differs")
        if ct.utf16_offset(text, start) != item["utf16_start"] or ct.utf16_offset(text, end) != item["utf16_end"]:
            problems.append(f"anchor {item['name']}: UTF-16 conversion differs")
        if ct.codepoint_offset(text, item["utf16_start"]) != start or ct.codepoint_offset(text, item["utf16_end"]) != end:
            problems.append(f"anchor {item['name']}: reverse conversion differs")
    return problems


def check_rules(c: ct.Contracts) -> list[str]:
    problems: list[str] = []
    rules = ct.load_json(ct.FIXTURES / "rules.json")
    for item in rules["approval"]:
        authorised, reasons = ct.approval_authorises(item["decision"], item["revision"], item["state"])
        if authorised != item["authorised"]:
            problems.append(f"approval {item['name']}: expected {item['authorised']}, got {authorised} ({reasons})")
        for expected in item["reasons_contain"]:
            if expected not in reasons:
                problems.append(f"approval {item['name']}: missing reason '{expected}' in {reasons}")
    for item in rules["public_read"]:
        served = ct.public_revision(item["state"], item["revisions"])
        served_id = served["id"] if served else None
        if served_id != item["serves"]:
            problems.append(f"public_read {item['name']}: expected {item['serves']}, got {served_id}")
    return problems


def check_content_rules(c: ct.Contracts) -> list[str]:
    """Construction-status consistency (D27) and first-person source reviews (D28)."""
    problems: list[str] = []
    rules = ct.content_rules()
    statuses = set(c.enum("common.schema.json#/$defs/ConstructionStatus"))
    perspectives = set(c.enum("common.schema.json#/$defs/ClaimPerspective"))
    if set(rules["occupancy_possible"]) != statuses:
        problems.append("content_rules occupancy_possible must cover exactly the ConstructionStatus values")
    if set(rules["wording"]["preferred_terms"]) != statuses:
        problems.append("content_rules preferred_terms must cover exactly the ConstructionStatus values")
    if not set(rules["export_labels"].values()) <= statuses:
        problems.append("content_rules export_labels map to unknown statuses")
    if not set(rules["occupancy_perspectives"]) <= perspectives:
        problems.append("content_rules occupancy_perspectives must be ClaimPerspective values")
    for project in ct.load_json(ROOT / "contracts" / "five-project-input-template.json")["projects"]:
        label = (project.get("client_ref") or {}).get("status")
        if label and ct.status_from_export_label(label, rules) is None:
            problems.append(f"{project['project_name']}: export status '{label}' has no construction status mapping")

    vectors = ct.load_json(ct.FIXTURES / "rules.json")
    for item in vectors["status_consistency"]:
        flags = ct.consistency_flags(item["perspective"], item["records"], item["phase_rera_id"], item["on_date"], rules)
        if flags != item["flags"]:
            problems.append(f"status_consistency {item['name']}: expected {item['flags']}, got {flags}")
    for item in vectors["status_wording"]:
        issues = ct.wording_issues(item["text"], item["status"], rules)
        if issues != {"blocking": item["blocking"], "advice": item["advice"]}:
            problems.append(f"status_wording {item['name']}: got {issues}")
    for item in vectors["review_rendering"]:
        found = ct.rendering_problems(item["original"], item["text"], item["rendering"], rules)
        if bool(found) != bool(item["problems_contain"]) or any(not any(f in p for p in found) for f in item["problems_contain"]):
            problems.append(f"review_rendering {item['name']}: expected {item['problems_contain']}, got {found}")
        if ct.rendering_check(item["original"], item["text"], item["rendering"]) != item["check"]:
            problems.append(f"review_rendering {item['name']}: check should be {item['check']}")

    for file_name, item in fixture_cases():
        if item["expect"] != "valid" or not item["schema"].endswith("/ReviewExcerpt"):
            continue
        review = item["instance"]
        if review["text"] is None:
            continue
        found = ct.rendering_problems(review["original_text"], review["text"], review["rendering"], rules)
        problems += [f"{file_name}:{item['name']}: {p}" for p in found]
    return problems


def check_seed(c: ct.Contracts) -> list[str]:
    """Step 01 data uses the same vocabulary as the contracts; the real input file matches its schema."""
    problems: list[str] = []
    statuses = set(c.enum("common.schema.json#/$defs/ConnectorStatus"))
    id_pattern = re.compile(c.resolve("common.schema.json#/$defs/ConnectorId")["pattern"])
    family_pattern = re.compile(c.resolve("common.schema.json#/$defs/PolicyFamily")["pattern"])
    connectors = ct.load_json(ROOT / "seed" / "connectors.json")
    for item in connectors["model_providers"] + connectors["connectors"]:
        if not id_pattern.match(item["id"]):
            problems.append(f"seed connector id {item['id']} does not match ConnectorId")
        if item["status"] not in statuses:
            problems.append(f"seed connector {item['id']}: status {item['status']} is not a ConnectorStatus")
    for policy in ct.load_json(ROOT / "seed" / "source_policies.json")["policies"]:
        if not family_pattern.match(policy["family"]):
            problems.append(f"seed policy family {policy['family']} does not match PolicyFamily")
    defaults = ct.load_json(ROOT / "seed" / "operating_defaults.json")["items"]
    if sorted(defaults["roles"]["value"]) != sorted(c.enum("common.schema.json#/$defs/Role")):
        problems.append("seed roles differ from the Role enum")
    if not isinstance(defaults.get("show_review_source_links", {}).get("value"), bool):
        problems.append("seed default show_review_source_links must be true or false (D28)")
    policies = {p["family"]: p for p in ct.load_json(ROOT / "seed" / "source_policies.json")["policies"]}
    for family in ("web_public_pages", "youtube"):
        if not policies[family]["quotation_allowed"]:
            problems.append(f"seed policy {family}: reviews quote authors' words, so quotation must be allowed (D28)")
    input_file = ct.load_json(ROOT / "contracts" / "five-project-input-template.json")
    problems += [f"project input file: {e}" for e in c.errors(input_file, "catalogue.schema.json#/$defs/ProjectInputFile")]
    return problems


def check_docs(c: ct.Contracts) -> list[str]:
    routes, machines, journeys = _docs()
    problems: list[str] = []
    expected = ct.render_journeys_doc(journeys, machines, routes)
    if not JOURNEYS_DOC.exists() or JOURNEYS_DOC.read_text(encoding="utf-8") != expected:
        problems.append("docs/10-journeys-and-states.md is stale: run scripts/check_contracts.py --render")
    screens = SCREENS_DOC.read_text(encoding="utf-8")
    referenced = set(re.findall(r"op:([A-Za-z]+)", screens))
    known = {route["operation_id"] for route in routes["routes"]}
    for op in sorted(referenced - known):
        problems.append(f"docs/09 references unknown operation op:{op}")
    for op in sorted(known - referenced - OPERATIONS_WITHOUT_SCREEN):
        problems.append(f"docs/09: operation {op} appears on no screen")
    return problems


def check_cross_language(c: ct.Contracts) -> list[str]:
    node = shutil.which("node")
    if node is None:
        return ["node not found: the JavaScript cross-check could not run (install Node.js)"]
    result = subprocess.run([node, str(ROOT / "scripts" / "jcs_check.mjs")], capture_output=True, text=True, cwd=ROOT)
    try:
        report = json.loads(result.stdout)
    except json.JSONDecodeError:
        return [f"jcs_check.mjs produced no report: {result.stderr.strip()[:300]}"]
    if result.returncode != 0 or report["problems"]:
        return [f"JavaScript: {p}" for p in report["problems"]] or ["jcs_check.mjs failed"]
    if report["checked"] < 10:
        return [f"JavaScript cross-check ran only {report['checked']} checks"]
    return []


SECTIONS: list[tuple[str, Callable[[ct.Contracts], list[str]]]] = [
    ("Schema files are valid and every $ref resolves", ct.check_schema_files),
    ("Status vocabulary and state machines", check_vocabulary),
    ("Route table and generated OpenAPI", check_api),
    ("Journeys: actors, operations and state paths", check_journeys),
    ("Agent outputs fit Claude structured outputs", check_agents),
    ("Fixtures: valid pass, invalid fail for the stated reason", check_fixtures),
    ("Canonical hashing (D23)", check_hashing),
    ("Text anchors, code points and UTF-16 (D24)", check_anchors),
    ("Approval and public-read rules", check_rules),
    ("Construction status and first-person source reviews (D27, D28)", check_content_rules),
    ("Step 01 seed data uses the contract vocabulary", check_seed),
    ("Docs: journeys doc current, screen references valid", check_docs),
    ("JavaScript cross-check (Node)", check_cross_language),
]


def run_all() -> list[dict[str, Any]]:
    contracts = ct.Contracts()
    results = []
    for title, check in SECTIONS:
        try:
            problems = check(contracts)
        except Exception as exc:  # noqa: BLE001 - a crashing check is a failed check
            problems = [f"check crashed: {type(exc).__name__}: {exc}"]
        results.append({"section": title, "problems": problems})
    return results


def summary_counts() -> dict[str, int]:
    routes, machines, journeys = _docs()
    contracts = ct.Contracts()
    return {
        "schema_files": len(contracts.schemas),
        "definitions": sum(len(s.get("$defs", {})) for s in contracts.schemas.values()),
        "operations": len(routes["routes"]),
        "state_machines": len(machines["machines"]),
        "journeys": len(journeys["journeys"]),
        "fixture_cases": len(fixture_cases()),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--render", action="store_true", help="regenerate docs/10-journeys-and-states.md before checking")
    parser.add_argument("--json", action="store_true", help="print the result as JSON")
    args = parser.parse_args(argv)
    if args.render:
        routes, machines, journeys = _docs()
        JOURNEYS_DOC.write_text(ct.render_journeys_doc(journeys, machines, routes), encoding="utf-8")
    results = run_all()
    failed = [r for r in results if r["problems"]]
    if args.json:
        print(json.dumps({"result": "fail" if failed else "pass", "counts": summary_counts(), "sections": results}, indent=2))
    else:
        counts = summary_counts()
        print("Step 02 contract checks")
        print("=======================")
        print(", ".join(f"{v} {k.replace('_', ' ')}" for k, v in counts.items()))
        print()
        for result in results:
            mark = "PASS" if not result["problems"] else f"FAIL ({len(result['problems'])})"
            print(f"  {mark:<9} {result['section']}")
            for problem in result["problems"][:10]:
                print(f"            - {problem}")
            if len(result["problems"]) > 10:
                print(f"            ... {len(result['problems']) - 10} more")
        print()
        print(f"Result: {'FAIL' if failed else 'PASS'} ({len(results) - len(failed)}/{len(results)} sections passed)")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
