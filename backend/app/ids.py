"""Opaque prefixed IDs: a three-letter type prefix and a ULID (D19, contracts/v1 common)."""

from __future__ import annotations

import re

from ulid import ULID

PREFIXES = {
    "prj",
    "usr",
    "src",
    "lnk",
    "seg",
    "evd",
    "clm",
    "fnd",
    "rev",
    "dec",
    "pub",
    "job",
    "run",
    "tsk",
    "pol",
    "cls",
    "aud",
    "del",
    "evl",
    "als",
    "cor",
    "rex",
}
ID_PATTERN = re.compile(r"^([a-z]{3})_[0-9A-HJKMNP-TV-Z]{26}$")


def new_id(prefix: str) -> str:
    if prefix not in PREFIXES:
        raise ValueError(f"unknown ID prefix {prefix!r}")
    return f"{prefix}_{ULID()}"


def id_prefix(value: str) -> str | None:
    match = ID_PATTERN.match(value)
    return match.group(1) if match else None
