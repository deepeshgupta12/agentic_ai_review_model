"""Naming conventions (D19), identical to scripts/validate_inputs.py; a test keeps them in step."""

from __future__ import annotations

import re
import unicodedata

SLUG_MAX_LENGTH = 80
RERA_FULL_PREFIX = "RC/REP/HARERA/"


def normalise_text(value: str) -> str:
    text = unicodedata.normalize("NFKC", value).casefold()
    kept = "".join(ch if unicodedata.category(ch)[0] in "LNM" else " " for ch in text)
    return " ".join(kept.split())


def slugify(*parts: str) -> str:
    text = unicodedata.normalize("NFKD", " ".join(parts)).encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    if len(slug) > SLUG_MAX_LENGTH:
        cut = slug[: SLUG_MAX_LENGTH + 1]
        slug = cut.rsplit("-", 1)[0] if "-" in cut else slug[:SLUG_MAX_LENGTH]
    return slug


def normalise_rera_id(value: str) -> str:
    text = re.sub(r"\s+", "", value).upper()
    return text[len(RERA_FULL_PREFIX) :] if text.startswith(RERA_FULL_PREFIX) else text


def match_key(project_name: str, city: str) -> str:
    return f"{normalise_text(project_name)}|{normalise_text(city)}"
