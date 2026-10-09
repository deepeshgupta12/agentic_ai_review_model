"""Text helpers for identity: normalised phrase search, RERA IDs, paragraph segments and text anchors (D19, D24).

Offsets are Unicode code points over NFC text, as the contracts require.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata

from app.identity.rules import NUMERAL_FORMS, UNIT_WORDS
from app.seed.normalise import normalise_rera_id, normalise_text

RERA_PATTERN = re.compile(
    r"(?:RC\s*/\s*REP\s*/\s*HARERA\s*/\s*)?[A-Z]{3}\s*/\s*\d{1,5}\s*/\s*\d{1,5}\s*/\s*\d{4}\s*/\s*\d{1,5}",
    re.IGNORECASE,
)
_PARAGRAPH_BREAK = re.compile(r"\n\s*\n")


DEVANAGARI_DIGITS = str.maketrans("०१२३४५६७८९", "0123456789")


def match_norm(text: str) -> str:
    """Normalised text for matching: Devanagari digits read as ASCII digits, so "सेक्टर १०२" is "सेक्टर 102" (I19)."""
    return normalise_text(text).translate(DEVANAGARI_DIGITS)


def nfc(text: str) -> str:
    return unicodedata.normalize("NFC", text)


def sha256_text(text: str) -> str:
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


def contains(haystack_norm: str, phrase_norm: str) -> bool:
    """Whole-word phrase search over normalised text."""
    return bool(phrase_norm) and f" {phrase_norm} " in f" {haystack_norm} "


def contains_unit_guarded(haystack_norm: str, phrase_norm: str) -> bool:
    """Like contains, but a phrase ending in a number does not match when a unit word follows it."""
    if not contains(haystack_norm, phrase_norm):
        return False
    if not phrase_norm.split()[-1].isdigit():
        return True
    tokens = haystack_norm.split()
    phrase = phrase_norm.split()
    for i in range(len(tokens) - len(phrase) + 1):
        if tokens[i : i + len(phrase)] == phrase:
            following = tokens[i + len(phrase)] if i + len(phrase) < len(tokens) else None
            if following not in UNIT_WORDS:
                return True
    return False


def without_phrases(haystack_norm: str, phrases: list[str]) -> str:
    """The text with every occurrence of the phrases removed (so a developer inside a project name is not counted)."""
    text = f" {haystack_norm} "
    for phrase in sorted({p for p in phrases if p}, key=len, reverse=True):
        text = text.replace(f" {phrase} ", " ")
    return " ".join(text.split())


def numeral_variants(name_norm: str) -> list[str]:
    """'phase 1' also as 'phase i' and 'phase one': the last token only, so names are not over-expanded."""
    tokens = name_norm.split()
    if not tokens:
        return []
    for forms in NUMERAL_FORMS:
        if tokens[-1] in forms:
            return [" ".join([*tokens[:-1], form]) for form in forms]
    return [name_norm]


def rera_ids_in(text: str) -> set[str]:
    return {normalise_rera_id(re.sub(r"\s+", "", m.group(0))) for m in RERA_PATTERN.finditer(text)}


def paragraphs(text: str) -> list[tuple[int, int]]:
    """Code-point spans of the non-empty paragraphs (blank-line separated), trimmed of surrounding whitespace."""
    spans: list[tuple[int, int]] = []
    start = 0
    for m in [*_PARAGRAPH_BREAK.finditer(text), None]:
        end = m.start() if m else len(text)
        block = text[start:end]
        stripped = block.strip()
        if stripped:
            left = start + (len(block) - len(block.lstrip()))
            spans.append((left, left + len(stripped)))
        if m:
            start = m.end()
    return spans


def text_anchor(text: str, start: int, end: int, representation: str = "original") -> dict[str, object]:
    if not 0 <= start < end <= len(text):
        raise ValueError("anchor outside the text")
    return {
        "kind": "text",
        "representation": representation,
        "unit": "codepoint",
        "start": start,
        "end": end,
        "excerpt_sha256": sha256_text(text[start:end]),
    }


__all__ = [
    "contains",
    "contains_unit_guarded",
    "nfc",
    "normalise_rera_id",
    "normalise_text",
    "numeral_variants",
    "paragraphs",
    "rera_ids_in",
    "sha256_text",
    "text_anchor",
    "without_phrases",
]
