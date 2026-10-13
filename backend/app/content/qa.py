"""Editorial QA of a page payload (Step 10.3-10.4; docs/08 final editorial quality checklist; D27, D28, D66).

Deterministic checks run on every revision, generated or edited, and decide whether it may reach final review:
- references: every substantive block (overview, advantages, considerations, questions) cites approved finding
  revisions of this page and claims of those findings; advantages rest on pros, considerations on cons;
- numbers: every number in a block (and in the heading, coverage note and metadata) appears in what it cites;
- attribution: a block resting only on reported opinions says whose view it is (an opinion never becomes a universal
  fact); the caveats of the cited findings are kept;
- construction status (D27): no occupancy words in the client's own text before possession;
- reviews (D28): each shown review is exactly an approved review as approved, with its credit line, and no dashes;
- balance: a nonblocking note when approved reviews or findings of the other side were left out.
A09 (app.content.editor) adds semantic issues on generated drafts. Neither can approve anything: a revision with a
blocking issue stays a draft, one without reaches final review for a person to approve.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from app.agents.common import numbers_in
from app.agents.consistency import rules

BLOCKS = ("overview", "advantages", "considerations", "questions")


@dataclass
class Basis:
    """What a payload may rest on: the selected approved findings and their claims, and the public form of each
    selected approved review."""

    project: dict[str, Any]
    findings: dict[tuple[str, int], dict[str, Any]]
    claims: dict[tuple[str, int], dict[str, Any]]
    reviews: dict[tuple[str, int], dict[str, Any]]  # review key -> expected PublicReview
    status: str | None  # construction status in force today (project level)
    left_out: dict[str, int] = field(default_factory=dict)  # approved but not selected, by polarity or kind


def issue(
    block: str, index: int | None, severity: str, category: str, explanation: str, source: str = "backend"
) -> dict[str, Any]:
    return {
        "block": block,
        "item_index": index,
        "severity": severity,
        "category": category,
        "explanation": explanation[:500],
        "source": source,
    }


def _words_pattern(terms: list[str]) -> re.Pattern[str]:
    return re.compile(r"\b(?:" + "|".join(re.escape(t) for t in sorted(terms, key=len, reverse=True)) + r")\b", re.I)


def _items(payload: dict[str, Any]) -> list[tuple[str, int | None, dict[str, Any]]]:
    out: list[tuple[str, int | None, dict[str, Any]]] = []
    if payload.get("overview") is not None:
        out.append(("overview", None, payload["overview"]))
    for block in ("advantages", "considerations", "questions"):
        out += [(block, i, item) for i, item in enumerate(payload.get(block) or [])]
    return out


def _text(block: str, item: dict[str, Any]) -> str:
    if block == "questions":
        return f"{item['question']} {item['answer']}"
    return f"{item['text']} {item.get('caveat') or ''}"


def check_payload(payload: dict[str, Any], basis: Basis) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    cues = _words_pattern(rules()["attribution"]["cues"])
    occupancy = _words_pattern(rules()["wording"]["occupancy_terms"])
    possible = rules()["occupancy_possible"].get(basis.status or "", None)
    place = basis.project
    # numbers in the project's own name and place ("Sector 102") may appear anywhere
    own_numbers = numbers_in(
        " ".join(str(place.get(k) or "") for k in ("project_name", "locality", "city", "micromarket"))
    )
    every_number: set[str] = set(own_numbers)
    for finding in basis.findings.values():
        every_number |= numbers_in(finding["wording"] + " " + " ".join(finding["caveats"]))
    for claim in basis.claims.values():
        every_number |= numbers_in(claim["statement"])

    for block, index, item in _items(payload):
        support = item["support"]
        cited = []
        for ref in support["findings"]:
            found = basis.findings.get((ref["id"], ref["revision"]))
            if found is None:
                issues.append(
                    issue(
                        block,
                        index,
                        "blocking",
                        "unsupported_claim",
                        f"cites finding {ref['id']} r{ref['revision']}, which is not an approved finding of this page",
                    )
                )
            else:
                cited.append(found)
        own_claims = {(c["id"], c["revision"]) for f in cited for c in f["claims"]}
        claims = []
        for ref in support["claims"]:
            key = (ref["id"], ref["revision"])
            if key not in own_claims or key not in basis.claims:
                issues.append(
                    issue(
                        block,
                        index,
                        "blocking",
                        "unsupported_claim",
                        f"cites claim {ref['id']} r{ref['revision']}, which none of its findings rests on",
                    )
                )
            else:
                claims.append(basis.claims[key])
        if not cited or not claims:
            issues.append(
                issue(
                    block, index, "blocking", "unsupported_claim", "a substantive block needs its findings and claims"
                )
            )
            continue
        kinds = {f["kind"] for f in cited}
        if block == "advantages" and ("pro" not in kinds or "con" in kinds):
            issues.append(issue(block, index, "blocking", "other", "an advantage must rest on pro findings only"))
        if block == "considerations" and ("con" not in kinds or "pro" in kinds):
            issues.append(issue(block, index, "blocking", "other", "a consideration must rest on con findings only"))
        text = _text(block, item)
        allowed = set(own_numbers)
        for finding in cited:
            allowed |= numbers_in(finding["wording"] + " " + " ".join(finding["caveats"]))
        for claim in claims:
            allowed |= numbers_in(claim["statement"])
        extra = numbers_in(text) - allowed
        if extra:
            issues.append(
                issue(
                    block,
                    index,
                    "blocking",
                    "number_mismatch",
                    f"numbers not in the cited findings or claims: {', '.join(sorted(extra))}",
                )
            )
        if all(f["attribution"] == "reported_opinion" for f in cited) and not cues.search(text):
            issues.append(
                issue(
                    block,
                    index,
                    "blocking",
                    "attribution_lost",
                    "rests only on reported opinions but does not say whose view it is",
                )
            )
        if block in ("advantages", "considerations"):  # the items that carry caveats (SupportedItem)
            caveat = (item.get("caveat") or "").casefold()
            lost = [c for f in cited for c in f["caveats"] if c.casefold() not in caveat]
            if lost:
                issues.append(
                    issue(block, index, "blocking", "caveat_lost", "caveat missing: " + "; ".join(dict.fromkeys(lost)))
                )

    own_text: list[tuple[str, int | None, str]] = [
        ("heading", None, payload["heading"]),
        ("coverage_note", None, payload["coverage_note"]),
    ]
    own_text += [("metadata", None, f"{payload['metadata']['title']} {payload['metadata']['description']}")]
    counts = {str(len(payload["reviews"])), str(len(basis.findings)), str(len(basis.reviews))}
    for block, index, text in own_text:
        extra = numbers_in(text) - every_number - counts
        if extra:
            issues.append(
                issue(
                    block,
                    index,
                    "blocking",
                    "number_mismatch",
                    f"numbers not in any cited record: {', '.join(sorted(extra))}",
                )
            )
    for block, index, item in _items(payload):
        own_text.append((block, index, _text(block, item)))
    for block, index, text in own_text:
        if occupancy.search(text):
            if possible == "no":
                issues.append(
                    issue(
                        block,
                        index,
                        "blocking",
                        "status_inconsistent",
                        "occupancy wording before possession; "
                        "write 'prospective buyers' or 'owners awaiting possession'",
                    )
                )
            elif possible == "phase_dependent":
                issues.append(
                    issue(
                        block, index, "nonblocking", "status_inconsistent", "partly ready project: name the ready phase"
                    )
                )
    if basis.project["project_name"].casefold() not in payload["heading"].casefold():
        issues.append(issue("heading", None, "blocking", "name_mismatch", "the heading must name the project"))

    forbidden = set(rules()["review_text"]["forbidden_characters"])
    for index, review in enumerate(payload["reviews"]):
        ref = review["support"]["review"]
        expected = basis.reviews.get((ref["id"], ref["revision"]))
        if expected is None:
            issues.append(
                issue(
                    "reviews",
                    index,
                    "blocking",
                    "review_meaning_changed",
                    "not an approved review selected for this page",
                )
            )
        elif review != expected:
            issues.append(
                issue(
                    "reviews",
                    index,
                    "blocking",
                    "review_meaning_changed",
                    "the shown review or its credit differs from the approved revision",
                )
            )
        if forbidden & set(review["text"]):
            issues.append(
                issue(
                    "reviews",
                    index,
                    "blocking",
                    "review_meaning_changed",
                    "displayed reviews have no dashes or hyphens",
                )
            )
    shown = [r["polarity"] for r in payload["reviews"]]
    for polarity, missing in basis.left_out.items():
        if missing and polarity in ("positive", "negative") and polarity not in shown and shown:
            issues.append(
                issue(
                    "reviews",
                    None,
                    "nonblocking",
                    "source_imbalance",
                    f"{missing} approved {polarity} review(s) are not on the page",
                )
            )
        if missing and polarity in ("pro", "con"):
            issues.append(
                issue(
                    "considerations" if polarity == "con" else "advantages",
                    None,
                    "nonblocking",
                    "source_imbalance",
                    f"{missing} approved {polarity} finding(s) were not selected",
                )
            )
    return issues


def summary(issues: list[dict[str, Any]], report_task: str | None) -> dict[str, Any]:
    blocking = sum(1 for i in issues if i["severity"] == "blocking")
    return {
        "status": "passed" if not issues else "issues_found",
        "blocking_issues": blocking,
        "nonblocking_issues": len(issues) - blocking,
        "report_task": report_task,
    }
