"""Context windows for evidence spans (Step 07.2; D50). See app.evidence.anchors for the rules."""

from __future__ import annotations

import re
from typing import Any

from app.identity.text import text_anchor

CONTEXT_PAD = 400
BOUNDARY = re.compile(r"(?<=[.!?।॥])\s+|\n+")  # the space after a sentence end, or a line break
SPACE = re.compile(r"\s+")


def text_context(text: str, start: int, end: int, pad: int = CONTEXT_PAD) -> dict[str, Any] | None:
    lo, hi = max(0, start - pad), min(len(text), end + pad)
    # Search the whole text between positions (not a slice), so the look-behind sees a sentence end just before lo.
    if lo > 0:  # begin at the first sentence (or, failing that, word) that starts inside the pad
        found = next(BOUNDARY.finditer(text, lo, start), None) or next(SPACE.finditer(text, lo, start), None)
        lo = found.end() if found else start
    if hi < len(text):  # end at the last sentence (or word) that ends inside the pad
        ends = [*BOUNDARY.finditer(text, end, hi)] or [*SPACE.finditer(text, end, hi)]
        hi = ends[-1].start() if ends else end
    lo, hi = min(lo, start), max(hi, end)
    if (lo, hi) == (start, end):
        return None
    return text_anchor(text, lo, hi)


def media_context(segments: list[dict[str, Any]], segment: dict[str, Any]) -> dict[str, Any] | None:
    """The previous and next speech windows around a speech window; frames have no context."""
    if segment["modality"] != "speech":
        return None
    speech = sorted((s for s in segments if s["modality"] == "speech"), key=lambda s: s["time"]["start_ms"])
    keys = [s["segment_key"] for s in speech]
    if segment["segment_key"] not in keys:
        return None
    i = keys.index(segment["segment_key"])
    first, last = speech[max(0, i - 1)], speech[min(len(speech) - 1, i + 1)]
    if first is last is segment:
        return None
    return {**segment["time"], "start_ms": first["time"]["start_ms"], "end_ms": last["time"]["end_ms"]}
