"""Language tags and quality flags for transcript windows (Step 06.4, D47). Deterministic and conservative: a flag
says a window needs care (code-switching, uncertain numbers, low confidence); it never changes the text."""

from __future__ import annotations

import re

from app.media.windows import Window

DEVANAGARI_WORD = re.compile(r"[ऀ-ॿ]+")
LATIN_WORD = re.compile(r"[A-Za-z]{2,}")
# Digits, Indian number words and units whose exact value matters in a claim (price, area, date, count).
NUMBER = re.compile(
    r"\d|\b(?:lakh|lakhs|lac|crore|crores|cr|hazaar|hazar|thousand|million|sq\.?\s?ft|square|gaj|bhk)\b"
    r"|लाख|करोड़|करोड|हज़ार|हजार|सौ|स्क्वायर|गज|बीएचके",
    re.IGNORECASE,
)
NOISE = re.compile(r"^\[[^\]]*\]$|^\([^)]*\)$")  # "[Music]", "[संगीत]", "(applause)"
LOW_LOGPROB = -1.0
NO_SPEECH = 0.6


def script_counts(text: str) -> tuple[int, int]:
    return len(DEVANAGARI_WORD.findall(text)), len(LATIN_WORD.findall(text))


def language_tag(text: str, declared: str | None) -> str:
    """BCP 47: hi for Devanagari Hindi, hi-Latn for Hindi written in Latin letters, else the declared language."""
    deva, latin = script_counts(text)
    base = (declared or "").split("-")[0].lower()
    if deva > latin:
        return "hi"
    if latin and base == "hi":
        return "hi-Latn"
    return declared or ("en" if latin else "und")


def quality_flags(window: Window, *, origin: str) -> list[str]:
    """origin: manual_captions | auto_captions | speech_to_text. Machine-made text (the last two) gets every number,
    amount, area or date flagged for a human check: the synthetic speech check (evals/media/v1) showed Hindi number
    words misspelt even when the rest of the sentence was right."""
    auto_captions = origin == "auto_captions"
    machine = origin in ("auto_captions", "speech_to_text")
    flags: list[str] = []
    deva, latin = script_counts(window.text)
    if min(deva, latin) >= 2:
        flags.append("code_switching")
    if window.cues and sum(1 for c in window.cues if NOISE.match(c.text)) * 2 >= len(window.cues):
        flags.append("music")
    probs = [c.avg_logprob for c in window.cues if c.avg_logprob is not None]
    low = bool(probs) and sum(probs) / len(probs) < LOW_LOGPROB
    if low:
        flags.append("low_confidence")
    if any((c.no_speech_prob or 0) > NO_SPEECH for c in window.cues):
        flags.append("low_audio_quality")
    if NUMBER.search(window.text) and (low or machine):
        flags.append("numbers_uncertain")
    if auto_captions:
        flags.append("auto_generated_captions")
    return flags
