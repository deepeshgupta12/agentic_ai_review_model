"""Deterministic project and phase matching (Step 04.4, 04.5). Pure functions; no database, no model.

For one source text it decides, per catalogue project, whether a segment names that project:
- identifiers are the project name, an approved alias (a context-required one only with the developer or
  locality nearby) or one of the project's RERA IDs; developer, locality, micromarket and city add context;
- a strong combination (a RERA ID, or an identifier with the locality or developer) at or above the
  threshold is auto-accepted; anything weaker goes to review;
- the same name with another city and none of the project's own place or developer is rejected;
- text naming several projects is split into paragraph segments when each paragraph names one project;
  otherwise every named project goes to review;
- a project whose search found the source but which the text never names is rejected.
Scores rank candidates for thresholds; they are not probabilities (contracts: rule_score).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.identity.catalogue import ApprovedAlias, ProjectIdentity
from app.identity.rules import AUTO_ACCEPT_SCORE, KNOWN_CITIES, MAX_SCORE, RULES_VERSION, WEIGHTS
from app.identity.text import (
    contains,
    contains_unit_guarded,
    nfc,
    normalise_text,
    numeral_variants,
    paragraphs,
    rera_ids_in,
    text_anchor,
    without_phrases,
)


@dataclass
class Segment:
    key: str  # whole | c:<start>-<end> | t:<start_ms>-<end_ms>
    text: str
    anchor: dict[str, Any] | None = None


@dataclass
class Candidate:
    project_id: str
    identifier: bool
    signals: list[str]
    score: int
    matched_alias: str | None
    phase: dict[str, Any]
    strong: bool
    own_place: bool
    conflicts: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


@dataclass
class MatchOutcome:
    project_id: str
    segment: Segment
    status: str  # auto_accepted | needs_review | rejected
    rule_score: int
    signals: list[str]
    matched_alias: str | None
    phase: dict[str, Any]
    rationale: str


def evaluate(identity: ProjectIdentity, text: str) -> Candidate:
    """Signals, score and phase for one project in one piece of text."""
    norm = normalise_text(text)
    signals: list[str] = []
    notes: list[str] = []
    score = 0
    matched: str | None = None

    name_hit = contains(norm, identity.name_norm)
    if name_hit:
        signals.append("project_name")
        score += WEIGHTS["project_name"]
        matched = identity.name

    own_rera = rera_ids_in(text) & identity.rera_ids
    if own_rera:
        signals.append("rera_id")
        score += WEIGHTS["rera_id"]

    aliases = [a for a in identity.aliases if a.normalised != identity.name_norm]
    alias_forms = {
        a.normalised: (numeral_variants(a.normalised) if a.target_kind == "phase" else [a.normalised]) for a in aliases
    }
    present = [a for a in aliases if any(contains_unit_guarded(norm, f) for f in alias_forms[a.normalised])]
    residual = without_phrases(norm, [identity.name_norm, *[f for a in present for f in alias_forms[a.normalised]]])
    developer = bool(identity.developer_norm) and contains(residual, identity.developer_norm or "")
    locality = any(contains(norm, v) for v in identity.locality_variants)
    micromarket = bool(identity.micromarket_norm) and contains(norm, identity.micromarket_norm or "")
    own_city = any(contains(norm, v) for v in identity.city_variants)
    context = developer or locality

    project_aliases: list[ApprovedAlias] = []
    phase_aliases: list[ApprovedAlias] = []
    for alias in sorted(present, key=lambda a: (a.mode != "standalone", -len(a.normalised))):
        if alias.mode == "context_required" and not context:
            notes.append(f"'{alias.text}' is context-required and appears without the developer or locality")
            continue
        (phase_aliases if alias.target_kind == "phase" else project_aliases).append(alias)
    if project_aliases:
        signals.append("approved_alias")
    if phase_aliases:
        signals.append("phase_name")
    if not name_hit and (project_aliases or phase_aliases):
        best = (project_aliases + phase_aliases)[0]
        score += WEIGHTS["approved_alias" if best.mode == "standalone" else "approved_alias_context"]
        matched = best.text
    if phase_aliases:
        score += WEIGHTS["phase_name"]

    for present_flag, name in (
        (developer, "developer"),
        (locality, "locality"),
        (micromarket, "micromarket"),
        (own_city, "city"),
    ):
        if present_flag:
            signals.append(name)
            score += WEIGHTS[name]

    identifier = name_hit or bool(own_rera) or bool(project_aliases) or bool(phase_aliases)
    conflicts: list[str] = []
    if identifier and not own_rera:
        own = {normalise_text(c) for c in identity.city_variants}
        others = [c for c in KNOWN_CITIES if c not in own and contains(norm, c)]
        others = [c for c in others if not any(c != o and contains(o, c) for o in others)]  # "delhi" inside "new delhi"
        if others:
            conflicts.append("other_city:" + ",".join(others))

    phase_ids = sorted(own_rera | {a.rera_id for a in phase_aliases if a.rera_id})
    if not identity.multi_phase:
        phase: dict[str, Any] = {"rera_id": None, "certainty": "not_applicable"}
    elif len(phase_ids) == 1:
        phase = {"rera_id": phase_ids[0], "certainty": "known"}
    else:
        phase = {"rera_id": None, "certainty": "unknown"}
        if len(phase_ids) > 1:
            notes.append("several phases are named")

    return Candidate(
        project_id=identity.id,
        identifier=identifier,
        signals=signals,
        score=min(score, MAX_SCORE),
        matched_alias=matched,
        phase=phase,
        strong=bool(own_rera) or (identifier and context),
        own_place=own_city or locality or developer,
        conflicts=conflicts,
        notes=notes,
    )


def decide(candidate: Candidate, *, extra_conflicts: list[str] | None = None) -> tuple[str, str]:
    """Status and rationale for a candidate that is linked."""
    conflicts = [*candidate.conflicts, *(extra_conflicts or [])]
    if not candidate.identifier:
        status, why = "rejected", "the text never names the project (no name, approved alias or RERA ID)"
    elif any(c.startswith("other_city") for c in conflicts) and not candidate.own_place:
        status, why = "rejected", "the name appears with another city and none of this project's place or developer"
    elif conflicts:
        status, why = "needs_review", "conflicting signals: " + "; ".join(conflicts)
    elif candidate.strong and candidate.score >= AUTO_ACCEPT_SCORE:
        status, why = "auto_accepted", "named with its place, developer or RERA ID"
    else:
        status, why = "needs_review", "named without enough place, developer or RERA context"
    parts = [
        why,
        f"signals: {', '.join(candidate.signals) or 'none'}",
        f"rule score {candidate.score} of {MAX_SCORE} (threshold {AUTO_ACCEPT_SCORE}, {RULES_VERSION})",
    ]
    if candidate.matched_alias:
        parts.append(f"matched by '{candidate.matched_alias}'")
    parts += candidate.notes
    return status, "; ".join(parts)


def _outcome(identity_id: str, segment: Segment, candidate: Candidate, extra: list[str] | None = None) -> MatchOutcome:
    status, rationale = decide(candidate, extra_conflicts=extra)
    return MatchOutcome(
        project_id=identity_id,
        segment=segment,
        status=status,
        rule_score=candidate.score,
        signals=candidate.signals,
        matched_alias=candidate.matched_alias,
        phase=candidate.phase,
        rationale=rationale,
    )


def _paragraph_segments(text: str, identities: list[ProjectIdentity]) -> dict[str, list[Segment]] | None:
    """Assign paragraph runs to projects when every paragraph names at most one project; else None."""
    spans = paragraphs(text)
    if len(spans) < 2:
        return None
    runs: dict[str, list[tuple[int, int]]] = {}
    current: str | None = None
    for start, end in spans:
        named = [i.id for i in identities if evaluate(i, text[start:end]).identifier]
        if len(named) > 1:
            return None
        if named:
            if named[0] != current or not runs.get(named[0]):
                runs.setdefault(named[0], []).append((start, end))
            else:
                runs[named[0]][-1] = (runs[named[0]][-1][0], end)
            current = named[0]
        elif current is not None:
            runs[current][-1] = (runs[current][-1][0], end)
    if len(runs) < 2:
        return None
    return {
        pid: [Segment(f"c:{s}-{e}", text[s:e], text_anchor(text, s, e)) for s, e in pid_runs]
        for pid, pid_runs in runs.items()
    }


def match_text(
    identities: list[ProjectIdentity],
    text: str,
    focus_project_ids: list[str] | None = None,
    segments: list[Segment] | None = None,
) -> list[MatchOutcome]:
    """Outcomes for every project the text names, plus a rejection for each focus project it does not name."""
    text = nfc(text)
    focus = list(dict.fromkeys(focus_project_ids or []))
    by_id = {i.id: i for i in identities}
    outcomes: list[MatchOutcome] = []

    if segments:  # pre-cut media segments: each stands alone
        for segment in segments:
            named = [(i, evaluate(i, segment.text)) for i in identities]
            named = [(i, c) for i, c in named if c.identifier]
            extra = ["multiple_projects"] if len(named) > 1 else None
            outcomes += [_outcome(i.id, segment, c, extra) for i, c in named]
    else:
        whole = Segment("whole", text, None)
        named = [(i, c) for i in identities if (c := evaluate(i, text)).identifier]
        split = _paragraph_segments(text, [i for i, _ in named]) if len(named) > 1 else None
        if split:
            for pid, pid_segments in split.items():
                outcomes += [_outcome(pid, s, evaluate(by_id[pid], s.text)) for s in pid_segments]
        else:
            extra = ["multiple_projects"] if len(named) > 1 else None
            outcomes += [_outcome(i.id, whole, c, extra) for i, c in named]

    linked = {o.project_id for o in outcomes}
    for pid in focus:
        if pid not in linked and pid in by_id:
            outcomes.append(_outcome(pid, Segment("whole", text, None), evaluate(by_id[pid], text)))
    return outcomes
