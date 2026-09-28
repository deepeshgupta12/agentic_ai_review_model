"""What matching knows about each catalogue project: names, place, developer, RERA registrations and the
approved aliases in its configuration. Unapproved alias proposals are never loaded here (D17)."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from pymongo.database import Database

from app.identity.rules import CITY_SYNONYMS
from app.identity.text import normalise_text, numeral_variants


@dataclass
class Phase:
    rera_id: str
    registered_name: str
    names_norm: list[str]


@dataclass
class ApprovedAlias:
    text: str
    normalised: str
    mode: str
    target_kind: str
    rera_id: str | None
    origin: str


@dataclass
class ProjectIdentity:
    id: str
    slug: str
    name: str
    name_norm: str
    city_variants: list[str]
    locality_variants: list[str]
    micromarket_norm: str | None
    developer_norm: str | None
    phases: list[Phase]
    aliases: list[ApprovedAlias] = field(default_factory=list)
    config_version: int = 0

    @property
    def multi_phase(self) -> bool:
        return len(self.phases) > 1

    @property
    def rera_ids(self) -> set[str]:
        return {p.rera_id for p in self.phases}

    def phase_for(self, rera_id: str | None) -> Phase | None:
        return next((p for p in self.phases if p.rera_id == rera_id), None)


def city_variants(city: str) -> list[str]:
    base = normalise_text(city)
    return [base, *[normalise_text(v) for v in CITY_SYNONYMS.get(base, [])]]


def locality_variants(locality: str) -> list[str]:
    """'Sector 76' also as 'sec 76' and 'sector76'; 'Manesar Sector 9' also as 'sector 9 manesar'."""
    base = normalise_text(locality)
    variants = [base]
    m = re.fullmatch(r"(?:(\w+) )?sector (\w+)", base)
    if m:
        place, number = m.group(1), m.group(2)
        forms = [f"sector {number}", f"sec {number}", f"sector{number}"]
        if place:
            variants += [f"{place} {f}" for f in forms[1:]] + [f"{f} {place}" for f in forms]
        else:
            variants += forms[1:]
    return list(dict.fromkeys(variants))


def identity_from_records(project: dict[str, Any], config: dict[str, Any] | None) -> ProjectIdentity:
    phases = [
        Phase(
            rera_id=r["id_normalised"],
            registered_name=r["registered_name"],
            names_norm=numeral_variants(normalise_text(r["registered_name"])),
        )
        for r in project.get("rera_registrations", [])
    ]
    aliases = [
        ApprovedAlias(
            text=a["text"],
            normalised=a["normalised"],
            mode=a["mode"],
            target_kind=a["target"]["kind"],
            rera_id=a["target"]["rera_id"],
            origin=a["origin"],
        )
        for a in (config or {}).get("aliases", [])
    ]
    return ProjectIdentity(
        id=project["_id"],
        slug=project["slug"],
        name=project["project_name"],
        name_norm=normalise_text(project["project_name"]),
        city_variants=city_variants(project["city"]),
        locality_variants=locality_variants(project["locality"]),
        micromarket_norm=normalise_text(project["micromarket"]) if project.get("micromarket") else None,
        developer_norm=normalise_text(project["developer"]) if project.get("developer") else None,
        phases=phases,
        aliases=aliases,
        config_version=(config or {}).get("version", 0),
    )


def load_identities(db: Database[dict[str, Any]], session: Any = None) -> list[ProjectIdentity]:
    configs = {c["_id"]: c for c in db["ai_project_configs"].find({}, session=session)}
    return [
        identity_from_records(p, configs.get(p["_id"])) for p in db["projects"].find({}, session=session).sort("_id", 1)
    ]
