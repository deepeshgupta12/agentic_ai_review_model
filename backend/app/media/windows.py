"""Transcript windows (D47). Caption lines and Whisper segments are short and uneven; they are grouped into windows
of about half a minute on the original timeline. A window is the stored media segment, the unit of project matching
and the span of speech evidence. Its text is the cues' text in order, unchanged apart from collapsed whitespace;
cue boundaries are never moved, so a timestamp always falls in the window that holds the words spoken then."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

SPACE = re.compile(r"\s+")


@dataclass(frozen=True)
class Cue:
    start_ms: int
    end_ms: int
    text: str
    avg_logprob: float | None = None  # Whisper's confidence; None for captions
    no_speech_prob: float | None = None


@dataclass
class Window:
    start_ms: int
    end_ms: int
    text: str
    cues: list[Cue] = field(default_factory=list)

    @property
    def key(self) -> str:
        return f"t:{self.start_ms}-{self.end_ms}"


def clean(text: str) -> str:
    return SPACE.sub(" ", text).strip()


def build_windows(
    cues: list[Cue], *, target_ms: int = 30_000, max_ms: int = 45_000, max_chars: int = 600, gap_ms: int = 2_500
) -> list[Window]:
    """Close a window once it reaches `target_ms`, before it would pass `max_ms` or `max_chars`, or at a pause
    longer than `gap_ms`. Overlapping cue times (rolling captions) are clipped so windows never overlap."""
    ordered = sorted((c for c in cues if clean(c.text)), key=lambda c: (c.start_ms, c.end_ms))
    groups: list[list[Cue]] = []
    current: list[Cue] = []
    for cue in ordered:
        cue = Cue(cue.start_ms, max(cue.end_ms, cue.start_ms + 1), clean(cue.text), cue.avg_logprob, cue.no_speech_prob)
        if current:
            start = current[0].start_ms
            last_end = max(c.end_ms for c in current)
            too_long = max(cue.end_ms, last_end) - start > max_ms
            too_much = sum(len(c.text) + 1 for c in current) + len(cue.text) > max_chars
            if last_end - start >= target_ms or too_long or too_much or cue.start_ms - last_end > gap_ms:
                groups.append(current)
                current = []
        current.append(cue)
    if current:
        groups.append(current)
    windows: list[Window] = []
    for i, group in enumerate(groups):
        start = group[0].start_ms if not windows else max(group[0].start_ms, windows[-1].end_ms)
        end = max(c.end_ms for c in group)
        if i + 1 < len(groups):
            end = min(end, groups[i + 1][0].start_ms)
        end = max(end, start + 1)
        windows.append(Window(start, end, " ".join(c.text for c in group), group))
    return windows


def window_at(windows: list[Window], ms: int) -> Window | None:
    """The window holding a moment of the original timeline (a timestamp jump), or None if none does."""
    for window in windows:
        if window.start_ms <= ms < window.end_ms:
            return window
    return None
