#!/usr/bin/env python3
"""Step 01 input validation.

Checks the five-project input file, the connector matrix, the source-policy
seed data, the operating defaults and the connector registry in DECISIONS.md,
and prints the registration preview (slugs and normalised search forms).

Standard library only, so it runs before the Step 03 toolchain exists.
Exit code 0 when every check passes, 1 otherwise.

    python3 scripts/validate_inputs.py            # report
    python3 scripts/validate_inputs.py --json     # machine-readable result
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
import unicodedata
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_PATHS = {
    "projects": ROOT / "contracts" / "five-project-input-template.json",
    "connectors": ROOT / "seed" / "connectors.json",
    "policies": ROOT / "seed" / "source_policies.json",
    "defaults": ROOT / "seed" / "operating_defaults.json",
    "decisions": ROOT / "DECISIONS.md",
}

EXPECTED_PROJECT_COUNT = 5  # D01
REQUIRED_PROJECT_FIELDS = ("project_name", "locality", "city")
OPTIONAL_TEXT_FIELDS = ("micromarket", "developer", "phase", "reference_url")
ALLOWED_PROJECT_FIELDS = set(REQUIRED_PROJECT_FIELDS) | set(OPTIONAL_TEXT_FIELDS) | {
    "alternate_names",
    "rera_ids",
    "client_ref",
}
CLIENT_REF_FIELDS = {"project_id", "city_id", "location_id", "sublocation_id", "status", "supplied_on"}
CLIENT_ID_FIELDS = ("project_id", "city_id", "location_id", "sublocation_id")

CONNECTOR_STATUSES = {"access_pending", "live", "unavailable"}
DEMO_REQUIREMENTS = {"mandatory", "one_of_group", "optional"}
CAPABILITY_KEYS = {"search", "archive", "comments", "transcripts", "deletion_check"}
CONNECTOR_TEXT_FIELDS = ("provider", "yields", "cursor_method", "deletion_method", "demonstration")
PROVIDER_TEXT_FIELDS = ("provider", "purpose", "demonstration")

POLICY_FLAGS = (
    "collection_allowed",
    "ai_processing_allowed",
    "quotation_allowed",
    "derived_publication_allowed",
    "attribution_required",
)
POLICY_STATUSES = {"proposed", "accepted"}

DEFAULT_STATUSES = {"proposed", "accepted", "open"}
REQUIRED_DEFAULTS = (
    "input_languages",
    "output_locale",
    "refresh_cadence",
    "discovery_lookback_days",
    "display_timezone",
    "roles",
    "seeded_users",
    "recurring_opinion_threshold",
    "freshness_warning_days",
    "withdrawal_serving_sla_minutes",
    "correction_owner",
    "public_page_indexing",
    "demo_environment",
)
ROLES = ("admin", "researcher", "moderator", "publisher", "analyst")  # docs/03

SLUG_MAX_LENGTH = 80
RERA_FULL_PREFIX = "RC/REP/HARERA/"
HARERA_ID = re.compile(r"^[A-Z]{3}/\d+/\d+/\d{4}/\d+$")
PLACEHOLDER = re.compile(r"<[^<>]*>")
ENV_NAME = re.compile(r"^[A-Z][A-Z0-9_]*$")
DIGITS = re.compile(r"^\d+$")
SECRET_LIKE = re.compile(
    r"sk-ant-[A-Za-z0-9_-]{8,}|gh[pousr]_[A-Za-z0-9]{20,}|AKIA[0-9A-Z]{16}|BEGIN [A-Z ]*PRIVATE KEY"
)
REGISTRY_HEADING = "## Connector registry"


# --- Conventions (D19) -------------------------------------------------------


def normalise_text(value: str) -> str:
    """Search form: NFKC, case-folded, punctuation to spaces, single spaces.

    Letters, digits and combining marks are kept, so Devanagari survives intact.
    """
    text = unicodedata.normalize("NFKC", value).casefold()
    kept = "".join(ch if unicodedata.category(ch)[0] in "LNM" else " " for ch in text)
    return " ".join(kept.split())


def slugify(*parts: str) -> str:
    """Lower-kebab ASCII slug, cut at a word boundary within SLUG_MAX_LENGTH."""
    text = unicodedata.normalize("NFKD", " ".join(parts)).encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    if len(slug) > SLUG_MAX_LENGTH:
        cut = slug[: SLUG_MAX_LENGTH + 1]
        slug = cut.rsplit("-", 1)[0] if "-" in cut else slug[:SLUG_MAX_LENGTH]
    return slug


def project_slug(project: dict[str, Any]) -> str:
    """Slug rule: project name, then locality, then city."""
    return slugify(project["project_name"], project["locality"], project["city"])


def normalise_rera_id(value: str) -> str:
    """Upper-case, no whitespace, full HARERA prefix removed so both forms compare equal."""
    text = re.sub(r"\s+", "", value).upper()
    return text[len(RERA_FULL_PREFIX):] if text.startswith(RERA_FULL_PREFIX) else text


# --- Helpers -------------------------------------------------------------------


def _is_text(value: Any) -> bool:
    return isinstance(value, str) and value.strip() != ""


def _has_placeholder(value: Any) -> bool:
    return isinstance(value, str) and bool(PLACEHOLDER.search(value))


def _is_iso_date(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    try:
        dt.date.fromisoformat(value)
    except ValueError:
        return False
    return True


def _project_label(index: int, project: Any) -> str:
    name = project.get("project_name") if isinstance(project, dict) else None
    return f"projects[{index}] ({name})" if _is_text(name) else f"projects[{index}]"


# --- Projects --------------------------------------------------------------------


def validate_projects(data: Any) -> tuple[list[str], list[str], list[dict[str, Any]]]:
    """Return (errors, warnings, registrations) for the five-project input file."""
    errors: list[str] = []
    warnings: list[str] = []
    registrations: list[dict[str, Any]] = []

    projects = data.get("projects") if isinstance(data, dict) else None
    if not isinstance(projects, list):
        return ["input file: 'projects' must be a list"], warnings, registrations
    if len(projects) != EXPECTED_PROJECT_COUNT:
        errors.append(
            f"input file: expected exactly {EXPECTED_PROJECT_COUNT} projects (D01), found {len(projects)}"
        )

    seen_slugs: dict[str, str] = {}
    seen_rera: dict[str, str] = {}
    seen_sy_ids: dict[str, str] = {}
    seen_names: dict[tuple[str, str], str] = {}

    for index, project in enumerate(projects):
        label = _project_label(index, project)
        if not isinstance(project, dict):
            errors.append(f"{label}: must be an object")
            continue

        for key in sorted(set(project) - ALLOWED_PROJECT_FIELDS):
            errors.append(f"{label}: unknown field '{key}'")

        required_ok = True
        for field in REQUIRED_PROJECT_FIELDS:
            value = project.get(field)
            if not _is_text(value):
                errors.append(f"{label}: required field '{field}' is missing or empty")
                required_ok = False
            elif _has_placeholder(value):
                errors.append(f"{label}: field '{field}' is still a placeholder: {value!r}")
                required_ok = False

        for field in OPTIONAL_TEXT_FIELDS:
            value = project.get(field)
            if value is None:
                continue
            if not _is_text(value):
                errors.append(f"{label}: optional field '{field}' must be null or non-empty text")
            elif _has_placeholder(value):
                errors.append(f"{label}: field '{field}' is still a placeholder: {value!r}")
        url = project.get("reference_url")
        if _is_text(url) and not url.startswith(("https://", "http://")):
            errors.append(f"{label}: reference_url must be an http(s) URL")

        alternate_names = project.get("alternate_names", [])
        if not isinstance(alternate_names, list):
            errors.append(f"{label}: alternate_names must be a list")
            alternate_names = []
        for name in alternate_names:
            if not _is_text(name):
                errors.append(f"{label}: alternate_names entries must be non-empty text")
            elif _has_placeholder(name):
                errors.append(f"{label}: alternate name is still a placeholder: {name!r}")

        rera_entries = project.get("rera_ids", [])
        if not isinstance(rera_entries, list):
            errors.append(f"{label}: rera_ids must be a list")
            rera_entries = []
        rera_normalised: list[str] = []
        registered_names: list[str] = []
        for entry in rera_entries:
            if not isinstance(entry, dict):
                errors.append(f"{label}: rera_ids entries must be objects with 'id' and 'registered_name' (D16)")
                continue
            for key in sorted(set(entry) - {"id", "registered_name"}):
                errors.append(f"{label}: rera_ids entry has unknown field '{key}'")
            rera_id, registered = entry.get("id"), entry.get("registered_name")
            if not _is_text(rera_id) or not _is_text(registered):
                errors.append(f"{label}: rera_ids entries need non-empty 'id' and 'registered_name' (D16)")
                continue
            normalised = normalise_rera_id(rera_id)
            if not HARERA_ID.match(normalised):
                warnings.append(f"{label}: RERA ID {rera_id!r} is not in the known HARERA format")
            if normalised in seen_rera:
                errors.append(f"{label}: RERA ID {rera_id!r} is already used by {seen_rera[normalised]}")
            seen_rera[normalised] = label
            rera_normalised.append(normalised)
            registered_names.append(registered)

        sy_ref = project.get("client_ref")
        if sy_ref is not None:
            if not isinstance(sy_ref, dict):
                errors.append(f"{label}: client_ref must be an object or null")
            else:
                missing = CLIENT_REF_FIELDS - set(sy_ref)
                extra = set(sy_ref) - CLIENT_REF_FIELDS
                if missing:
                    errors.append(f"{label}: client_ref is missing {sorted(missing)}")
                if extra:
                    errors.append(f"{label}: client_ref has unknown fields {sorted(extra)}")
                for key in CLIENT_ID_FIELDS:
                    if key in sy_ref and not (isinstance(sy_ref[key], str) and DIGITS.match(sy_ref[key])):
                        errors.append(f"{label}: client_ref.{key} must be a string of digits")
                if "supplied_on" in sy_ref and not _is_iso_date(sy_ref["supplied_on"]):
                    errors.append(f"{label}: client_ref.supplied_on must be an ISO date (YYYY-MM-DD)")
                sy_id = sy_ref.get("project_id")
                if isinstance(sy_id, str) and sy_id in seen_sy_ids:
                    errors.append(f"{label}: the client project_id {sy_id} is already used by {seen_sy_ids[sy_id]}")
                if isinstance(sy_id, str):
                    seen_sy_ids[sy_id] = label

        if not required_ok:
            continue

        slug = project_slug(project)
        if not slug:
            errors.append(f"{label}: slug is empty after ASCII folding; add a Latin-script name")
        elif slug in seen_slugs:
            errors.append(f"{label}: slug '{slug}' duplicates {seen_slugs[slug]} (probable duplicate project)")
        else:
            seen_slugs[slug] = label

        name_key = (normalise_text(project["project_name"]), normalise_text(project["city"]))
        if name_key in seen_names:
            warnings.append(f"{label}: same name and city as {seen_names[name_key]}; confirm these are different projects")
        seen_names.setdefault(name_key, label)

        search_names: list[str] = []
        for name in [project["project_name"], *alternate_names, *registered_names]:
            form = normalise_text(name) if _is_text(name) else ""
            if form and form not in search_names:
                search_names.append(form)
                if " " not in form:
                    warnings.append(
                        f"{label}: search name '{form}' is a single word; Step 04 should use it only with developer or locality (D17)"
                    )

        registrations.append(
            {
                "index": index + 1,
                "project_name": project["project_name"],
                "slug": slug,
                "search_names": search_names,
                "locality": normalise_text(project["locality"]),
                "micromarket": normalise_text(project["micromarket"]) if _is_text(project.get("micromarket")) else None,
                "city": normalise_text(project["city"]),
                "developer": normalise_text(project["developer"]) if _is_text(project.get("developer")) else None,
                "rera_ids": rera_normalised,
                "client_project_id": sy_ref.get("project_id") if isinstance(sy_ref, dict) else None,
            }
        )

    return errors, warnings, registrations


# --- Source policies ---------------------------------------------------------------


def validate_policies(data: Any) -> tuple[list[str], list[str], dict[str, dict[str, Any]]]:
    """Return (errors, warnings, policies by family)."""
    errors: list[str] = []
    warnings: list[str] = []
    by_family: dict[str, dict[str, Any]] = {}

    policies = data.get("policies") if isinstance(data, dict) else None
    if not isinstance(policies, list) or not policies:
        return ["source policies: 'policies' must be a non-empty list"], warnings, by_family

    for index, policy in enumerate(policies):
        if not isinstance(policy, dict) or not _is_text(policy.get("family")):
            errors.append(f"policies[{index}]: must be an object with a 'family'")
            continue
        family = policy["family"]
        label = f"policy '{family}'"
        if family in by_family:
            errors.append(f"{label}: duplicate family")
            continue
        by_family[family] = policy

        version = policy.get("policy_version")
        if not isinstance(version, int) or isinstance(version, bool) or version < 1:
            errors.append(f"{label}: policy_version must be an integer >= 1")
        flags_ok = True
        for flag in POLICY_FLAGS:
            if not isinstance(policy.get(flag), bool):
                errors.append(f"{label}: '{flag}' must be true or false")
                flags_ok = False
        if policy.get("status") not in POLICY_STATUSES:
            errors.append(f"{label}: status must be one of {sorted(POLICY_STATUSES)}")
        for field in ("basis", "review_owner"):
            if not _is_text(policy.get(field)):
                errors.append(f"{label}: '{field}' must be non-empty text")
        for field in ("hosts", "excluded_hosts", "conditions"):
            value = policy.get(field, [])
            if not isinstance(value, list) or not all(_is_text(item) for item in value):
                errors.append(f"{label}: '{field}' must be a list of non-empty text")

        retention = policy.get("retention_days")
        if retention is not None and (not isinstance(retention, int) or isinstance(retention, bool) or retention < 0):
            errors.append(f"{label}: retention_days must be null or a non-negative integer")
            retention = None
        if not flags_ok:
            continue

        # Permission chain: each right needs the one before it.
        if policy["ai_processing_allowed"] and not policy["collection_allowed"]:
            errors.append(f"{label}: AI processing allowed without collection")
        if policy["derived_publication_allowed"] and not policy["ai_processing_allowed"]:
            errors.append(f"{label}: derived publication allowed without AI processing")
        if policy["quotation_allowed"] and not policy["derived_publication_allowed"]:
            errors.append(f"{label}: quotation allowed without derived publication")
        if policy["derived_publication_allowed"] and not policy["attribution_required"]:
            errors.append(f"{label}: derived publication requires attribution")
        if policy["collection_allowed"] and not (isinstance(retention, int) and retention > 0):
            errors.append(f"{label}: collection allowed without a positive retention_days")
        if not policy["collection_allowed"] and retention not in (None, 0):
            errors.append(f"{label}: retention_days set although collection is not allowed")

    # A host owned by another family must not be reachable through the generic web route.
    generic = by_family.get("web_public_pages")
    if generic is not None and isinstance(generic.get("excluded_hosts"), list):
        excluded = set(generic["excluded_hosts"])
        for family, policy in by_family.items():
            if family == "web_public_pages" or not isinstance(policy.get("hosts"), list):
                continue
            for host in policy["hosts"]:
                if host not in excluded:
                    errors.append(
                        f"policy 'web_public_pages': host '{host}' belongs to '{family}' and must be in excluded_hosts"
                    )

    return errors, warnings, by_family


# --- Connectors ---------------------------------------------------------------------


def _check_status(label: str, item: dict[str, Any], errors: list[str]) -> None:
    status = item.get("status")
    if status not in CONNECTOR_STATUSES:
        errors.append(f"{label}: status must be one of {sorted(CONNECTOR_STATUSES)}")
    elif status == "live":
        # docs/06: live only after a real credential and a recorded demonstration.
        if not _is_iso_date(item.get("last_verified")) or not _is_text(item.get("verification_ref")):
            errors.append(f"{label}: 'live' requires last_verified (date) and verification_ref (recorded demonstration)")
    elif status == "unavailable" and not _is_text(item.get("unavailable_reason")):
        errors.append(f"{label}: 'unavailable' requires unavailable_reason")
    if item.get("last_verified") is not None and not _is_iso_date(item.get("last_verified")):
        errors.append(f"{label}: last_verified must be null or an ISO date")


def _check_credentials(label: str, item: dict[str, Any], errors: list[str]) -> None:
    env = item.get("credential_env")
    if not isinstance(env, list) or not all(isinstance(name, str) and ENV_NAME.match(name) for name in env):
        errors.append(f"{label}: credential_env must be a list of UPPER_SNAKE_CASE variable names")
    elif not env and not _is_text(item.get("no_credential_reason")):
        errors.append(f"{label}: no credential listed, so no_credential_reason is required")


def _check_order_and_requirement(label: str, item: dict[str, Any], errors: list[str]) -> None:
    order = item.get("acquisition_order")
    if not isinstance(order, int) or isinstance(order, bool) or order < 1:
        errors.append(f"{label}: acquisition_order must be an integer >= 1")
    requirement = item.get("demo_requirement")
    if requirement not in DEMO_REQUIREMENTS:
        errors.append(f"{label}: demo_requirement must be one of {sorted(DEMO_REQUIREMENTS)}")
    elif requirement == "one_of_group" and not _is_text(item.get("group")):
        errors.append(f"{label}: demo_requirement 'one_of_group' requires a group")


def validate_connectors(data: Any, policy_families: set[str]) -> tuple[list[str], list[str]]:
    """Return (errors, warnings) for the connector matrix and model providers."""
    errors: list[str] = []
    warnings: list[str] = []
    if not isinstance(data, dict):
        return ["connector matrix: must be an object"], warnings
    if not _is_text(data.get("credential_location")):
        errors.append("connector matrix: 'credential_location' must say where secrets live")

    providers = data.get("model_providers")
    connectors = data.get("connectors")
    if not isinstance(providers, list) or not providers:
        errors.append("connector matrix: 'model_providers' must be a non-empty list")
        providers = []
    if not isinstance(connectors, list) or not connectors:
        errors.append("connector matrix: 'connectors' must be a non-empty list")
        connectors = []

    seen_ids: set[str] = set()
    groups: dict[str, list[str]] = {}

    for index, provider in enumerate(providers):
        if not isinstance(provider, dict) or not _is_text(provider.get("id")):
            errors.append(f"model_providers[{index}]: must be an object with an 'id'")
            continue
        label = f"model provider '{provider['id']}'"
        if provider["id"] in seen_ids:
            errors.append(f"{label}: duplicate id")
        seen_ids.add(provider["id"])
        for field in PROVIDER_TEXT_FIELDS:
            if not _is_text(provider.get(field)):
                errors.append(f"{label}: '{field}' must be non-empty text")
        _check_order_and_requirement(label, provider, errors)
        _check_credentials(label, provider, errors)
        _check_status(label, provider, errors)

    for index, connector in enumerate(connectors):
        if not isinstance(connector, dict) or not _is_text(connector.get("id")):
            errors.append(f"connectors[{index}]: must be an object with an 'id'")
            continue
        label = f"connector '{connector['id']}'"
        if connector["id"] in seen_ids:
            errors.append(f"{label}: duplicate id")
        seen_ids.add(connector["id"])

        for field in CONNECTOR_TEXT_FIELDS:
            if not _is_text(connector.get(field)):
                errors.append(f"{label}: '{field}' must be non-empty text")
        family = connector.get("policy_family")
        if family not in policy_families:
            errors.append(f"{label}: policy_family '{family}' has no source policy")
        kinds = connector.get("content_kinds")
        if not isinstance(kinds, list) or not kinds or not all(_is_text(kind) for kind in kinds):
            errors.append(f"{label}: content_kinds must be a non-empty list")
        capabilities = connector.get("expected_capabilities")
        if not isinstance(capabilities, dict) or set(capabilities) != CAPABILITY_KEYS:
            errors.append(f"{label}: expected_capabilities must have exactly {sorted(CAPABILITY_KEYS)}")
        elif not all(value in (True, False, None) for value in capabilities.values()):
            errors.append(f"{label}: expected_capabilities values must be true, false or null")
        if connector.get("quota") is not None and not isinstance(connector.get("quota"), dict):
            errors.append(f"{label}: quota must be null until verified, then an object")

        _check_order_and_requirement(label, connector, errors)
        if connector.get("demo_requirement") == "one_of_group" and _is_text(connector.get("group")):
            groups.setdefault(connector["group"], []).append(connector["id"])
        _check_credentials(label, connector, errors)
        _check_status(label, connector, errors)

    for group, members in groups.items():
        if len(members) < 2:
            errors.append(f"connector group '{group}': one_of_group needs at least two connectors, found {members}")

    return errors, warnings


# --- Operating defaults -------------------------------------------------------------


def validate_defaults(data: Any) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    items = data.get("items") if isinstance(data, dict) else None
    if not isinstance(items, dict):
        return ["operating defaults: 'items' must be an object"], warnings

    for key in REQUIRED_DEFAULTS:
        if key not in items:
            errors.append(f"operating defaults: missing item '{key}'")

    for key, item in items.items():
        label = f"default '{key}'"
        if not isinstance(item, dict) or "value" not in item:
            errors.append(f"{label}: must be an object with a 'value'")
            continue
        status = item.get("status")
        if status not in DEFAULT_STATUSES:
            errors.append(f"{label}: status must be one of {sorted(DEFAULT_STATUSES)}")
        if not _is_text(item.get("ref")):
            errors.append(f"{label}: 'ref' must name the input or spec it answers")
        value = item["value"]
        if status == "open" and value not in (None, [], ""):
            errors.append(f"{label}: an open item cannot have a value yet")
        if status in ("proposed", "accepted") and value in (None, [], ""):
            errors.append(f"{label}: a {status} item needs a value")
        if status == "accepted" and not (_is_iso_date(item.get("accepted_on")) and _is_text(item.get("accepted_by"))):
            errors.append(f"{label}: accepted items need accepted_on (date) and accepted_by")

    roles = items.get("roles", {})
    if isinstance(roles, dict) and roles.get("value") is not None and sorted(roles["value"]) != sorted(ROLES):
        errors.append(f"default 'roles': must be exactly {list(ROLES)} (docs/03)")
    languages = items.get("input_languages", {})
    if isinstance(languages, dict) and isinstance(languages.get("value"), list):
        for tag in languages["value"]:
            if not (isinstance(tag, str) and re.match(r"^[a-z]{2,3}(-[A-Za-z0-9]{2,8})*$", tag)):
                errors.append(f"default 'input_languages': {tag!r} is not a language tag")
    return errors, warnings


# --- Decision register and secrets ---------------------------------------------------


def registry_section(decisions_text: str) -> str | None:
    start = decisions_text.find(REGISTRY_HEADING)
    if start == -1:
        return None
    end = decisions_text.find("\n## ", start + len(REGISTRY_HEADING))
    return decisions_text[start:] if end == -1 else decisions_text[start:end]


def check_decisions_registry(decisions_text: str, connector_data: Any) -> list[str]:
    """Every connector and model provider has a registry row showing its current status."""
    section = registry_section(decisions_text)
    if section is None:
        return [f"DECISIONS.md: missing '{REGISTRY_HEADING}' section"]
    lines = section.splitlines()
    errors: list[str] = []
    items = []
    if isinstance(connector_data, dict):
        for key in ("model_providers", "connectors"):
            if isinstance(connector_data.get(key), list):
                items.extend(item for item in connector_data[key] if isinstance(item, dict))
    for item in items:
        marker = f"`{item.get('id')}`"
        rows = [line for line in lines if line.startswith("|") and marker in line]
        if not rows:
            errors.append(f"DECISIONS.md registry: no row for {marker}")
        elif not any(str(item.get("status")) in row for row in rows):
            errors.append(f"DECISIONS.md registry: row for {marker} does not show status '{item.get('status')}'")
    return errors


def scan_for_secrets(texts: dict[str, str]) -> list[str]:
    return [f"{name}: contains a secret-like value" for name, text in texts.items() if SECRET_LIKE.search(text)]


# --- Runner ----------------------------------------------------------------------------


def _display(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(ROOT))
    except ValueError:
        return str(path)


def run(paths: dict[str, Path]) -> dict[str, Any]:
    errors: list[str] = []
    warnings: list[str] = []
    texts: dict[str, str] = {}
    data: dict[str, Any] = {}

    for key, path in paths.items():
        try:
            texts[key] = path.read_text(encoding="utf-8")
        except OSError as exc:
            errors.append(f"{_display(path)}: cannot read ({exc.strerror})")
            continue
        if key != "decisions":
            try:
                data[key] = json.loads(texts[key])
            except json.JSONDecodeError as exc:
                errors.append(f"{_display(path)}: invalid JSON at line {exc.lineno}: {exc.msg}")

    registrations: list[dict[str, Any]] = []
    policies: dict[str, dict[str, Any]] = {}
    if "projects" in data:
        e, w, registrations = validate_projects(data["projects"])
        errors += e
        warnings += w
    if "policies" in data:
        e, w, policies = validate_policies(data["policies"])
        errors += e
        warnings += w
    if "connectors" in data:
        e, w = validate_connectors(data["connectors"], set(policies))
        errors += e
        warnings += w
        if "decisions" in texts:
            errors += check_decisions_registry(texts["decisions"], data["connectors"])
    if "defaults" in data:
        e, w = validate_defaults(data["defaults"])
        errors += e
        warnings += w
    errors += scan_for_secrets({_display(paths[k]): t for k, t in texts.items() if k != "decisions"})

    connectors = data.get("connectors", {}) if isinstance(data.get("connectors"), dict) else {}
    all_sources = [
        item
        for key in ("model_providers", "connectors")
        for item in (connectors.get(key) or [])
        if isinstance(item, dict)
    ]
    defaults = data.get("defaults", {}).get("items", {}) if isinstance(data.get("defaults"), dict) else {}
    summary = {
        "projects": len(registrations),
        "connectors": {
            "total": len(all_sources),
            "by_status": _count(item.get("status") for item in all_sources),
        },
        "policies": {"total": len(policies), "by_status": _count(p.get("status") for p in policies.values())},
        "defaults": {
            "total": len(defaults) if isinstance(defaults, dict) else 0,
            "by_status": _count(i.get("status") for i in defaults.values() if isinstance(i, dict))
            if isinstance(defaults, dict)
            else {},
        },
    }
    return {
        "result": "pass" if not errors else "fail",
        "errors": errors,
        "warnings": warnings,
        "registrations": registrations,
        "summary": summary,
        "files": {key: _display(path) for key, path in paths.items()},
    }


def _count(values: Any) -> dict[str, int]:
    counts: dict[str, int] = {}
    for value in values:
        counts[str(value)] = counts.get(str(value), 0) + 1
    return dict(sorted(counts.items()))


def render_report(result: dict[str, Any]) -> str:
    out = ["Step 01 input validation", "========================", ""]
    out.append(f"Projects ({result['files'].get('projects')})")
    for reg in result["registrations"]:
        out.append(f"  {reg['index']}. {reg['project_name']}")
        out.append(f"     slug:         {reg['slug']}")
        out.append(f"     search names: {' | '.join(reg['search_names'])}")
        place = ", ".join(part for part in (reg["locality"], reg["micromarket"], reg["city"]) if part)
        out.append(f"     place:        {place}")
        out.append(f"     developer:    {reg['developer'] or '-'}")
        out.append(f"     RERA:         {', '.join(reg['rera_ids']) or '-'}")
        out.append(f"     Client id:        {reg['client_project_id'] or '-'}")
    summary = result["summary"]

    def fmt(counts: dict[str, int]) -> str:
        return ", ".join(f"{count} {status}" for status, count in counts.items()) or "none"

    out += [
        "",
        f"Connectors + model providers: {summary['connectors']['total']} ({fmt(summary['connectors']['by_status'])})",
        f"Source policies: {summary['policies']['total']} ({fmt(summary['policies']['by_status'])})",
        f"Operating defaults: {summary['defaults']['total']} ({fmt(summary['defaults']['by_status'])})",
        "",
    ]
    if result["warnings"]:
        out.append(f"Warnings ({len(result['warnings'])}):")
        out += [f"  - {w}" for w in result["warnings"]]
        out.append("")
    if result["errors"]:
        out.append(f"Errors ({len(result['errors'])}):")
        out += [f"  - {e}" for e in result["errors"]]
        out.append("")
    verdict = "PASS" if result["result"] == "pass" else "FAIL"
    out.append(f"Result: {verdict} ({len(result['errors'])} errors, {len(result['warnings'])} warnings)")
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    for key, path in DEFAULT_PATHS.items():
        parser.add_argument(f"--{key}", type=Path, default=path, help=f"default: {_display(path)}")
    parser.add_argument("--json", action="store_true", help="print the result as JSON")
    args = parser.parse_args(argv)

    result = run({key: getattr(args, key) for key in DEFAULT_PATHS})
    print(json.dumps(result, indent=2, ensure_ascii=False) if args.json else render_report(result))
    return 0 if result["result"] == "pass" else 1


if __name__ == "__main__":
    sys.exit(main())
