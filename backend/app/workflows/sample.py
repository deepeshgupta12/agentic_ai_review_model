"""The sample sheet for the product owner's review of real outputs (Step 08, D53).

Per project, a deterministic sample of stored claims (spread over verified, disputed and unverified facts,
allegations, opinions, promotions and flagged claims), every open or approved finding and some reviews, each with the
words it rests on and where they came from, plus empty columns for the reviewer's verdict. The sheet quotes
third-party posts, so it is written for a person to read and never committed (`exports/` is git-ignored).
"""

from __future__ import annotations

import csv
import hashlib
import io
from typing import Any

from pymongo.database import Database

COLUMNS = [
    "no",
    "project",
    "item",
    "id",
    "aspect",
    "kind or type",
    "polarity",
    "perspective or credit",
    "verification or attribution",
    "statement, wording or review text",
    "caveats, flags or rendering",
    "evidence (original words, shortened)",
    "source",
    "published",
    "correct? (yes / no / partly)",
    "what is wrong",
    "comment",
]
GROUPS = ("verified", "contradicted", "disputed", "flagged", "allegation", "fact", "opinion", "promotion")


def _order(record_id: str) -> str:
    return hashlib.sha256(record_id.encode()).hexdigest()


def _group(claim: dict[str, Any]) -> str:
    status = claim["verification"]["status"]
    if status in ("verified", "contradicted", "disputed"):
        return status
    return "flagged" if claim["consistency_flags"] else claim["claim_type"]


def _evidence(db: Database[dict[str, Any]], refs: list[dict[str, Any]]) -> tuple[str, str, str]:
    words, sources, dates = [], [], []
    for ref in refs[:2]:
        evidence = db["ai_evidence"].find_one({"id": ref["id"], "revision": ref["revision"]})
        if evidence is None:
            continue
        words.append(" ".join((evidence.get("excerpt_text") or "[erased]").split())[:300])
        source = db["ai_sources"].find_one({"id": evidence["source"]["id"], "revision": evidence["source"]["revision"]})
        if source:
            sources.append(source["canonical_url"])
            value = (source.get("publication_date") or {}).get("value")
            dates.append(str(value)[:10] if value else "unknown")
    return " | ".join(words), " | ".join(sources), " | ".join(dates)


def sample_rows(
    db: Database[dict[str, Any]], claims_per_project: int = 10, reviews_per_project: int = 4
) -> list[list[str]]:
    rows: list[list[str]] = []
    for project in db["projects"].find({}, {"project_name": 1}).sort("slug", 1):
        name = project["project_name"]
        latest: dict[str, dict[str, Any]] = {}
        for claim in db["ai_claims"].find({"project_id": project["_id"]}).sort("revision", 1):
            latest[claim["id"]] = claim
        by_group: dict[str, list[dict[str, Any]]] = {g: [] for g in GROUPS}
        for claim in sorted(latest.values(), key=lambda c: _order(c["id"])):
            by_group[_group(claim)].append(claim)
        chosen: list[dict[str, Any]] = []
        while len(chosen) < claims_per_project and any(by_group.values()):
            for group in GROUPS:  # round robin over the groups, so rare kinds are seen
                if by_group[group] and len(chosen) < claims_per_project:
                    chosen.append(by_group[group].pop(0))
        for claim in chosen:
            words, sources, dates = _evidence(db, claim["supporting_evidence"])
            reason = claim["verification"].get("reason") or ""
            rows.append(
                [
                    name,
                    "claim",
                    f"{claim['id']}@{claim['revision']}",
                    claim["aspect"] + (f" ({claim['aspect_label']})" if claim.get("aspect_label") else ""),
                    claim["claim_type"],
                    claim["polarity"],
                    claim["perspective"],
                    claim["verification"]["status"] + (f": {reason}" if reason else ""),
                    claim["statement"],
                    ", ".join(claim["consistency_flags"]) + f" origins: {claim['independent_origin_count']}",
                    words,
                    sources,
                    dates,
                ]
            )
        findings = db["ai_findings"].find(
            {"project_id": project["_id"], "review_status": {"$in": ["pending", "changes_requested", "approved"]}}
        )
        for finding in sorted(findings, key=lambda f: (f["aspect"], f["kind"])):
            refs: list[dict[str, Any]] = []
            for ref in finding["claims"][:2]:
                cited = db["ai_claims"].find_one({"id": ref["id"], "revision": ref["revision"]})
                refs += cited["supporting_evidence"][:1] if cited else []
            words, sources, dates = _evidence(db, refs)
            rows.append(
                [
                    name,
                    "finding",
                    f"{finding['id']}@{finding['revision']}",
                    finding["aspect"],
                    finding["kind"],
                    "",
                    "",
                    f"{finding['attribution']}; {len(finding['claims'])} claim(s), "
                    f"{finding['independent_origin_count']} origin(s)",
                    finding["wording"],
                    "; ".join(finding["caveats"]),
                    words,
                    sources,
                    dates,
                ]
            )
        reviews = db["ai_review_excerpts"].find(
            {"project_id": project["_id"], "review_status": {"$in": ["pending", "changes_requested", "approved"]}}
        )
        for review in sorted(reviews, key=lambda r: _order(r["id"]))[:reviews_per_project]:
            source = db["ai_sources"].find_one({"id": review["source"]["id"], "revision": review["source"]["revision"]})
            value = (review.get("published") or {}).get("value")
            rows.append(
                [
                    name,
                    "review",
                    f"{review['id']}@{review['revision']}",
                    ", ".join(review["aspects"]),
                    review["source_kind"],
                    review["polarity"],
                    review["speaker_label"],
                    "",
                    review["text"] or "[erased]",
                    f"{review['rendering']}"
                    + (f"; flags: {', '.join(review['consistency_flags'])}" if review["consistency_flags"] else ""),
                    " ".join((review["original_text"] or "[erased]").split())[:300],
                    source["canonical_url"] if source else "",
                    str(value)[:10] if value else "unknown",
                ]
            )
    return [[str(n), *row, "", "", ""] for n, row in enumerate(rows, start=1)]


def sample_csv(db: Database[dict[str, Any]], claims_per_project: int = 10, reviews_per_project: int = 4) -> str:
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(COLUMNS)
    writer.writerows(sample_rows(db, claims_per_project, reviews_per_project))
    return "﻿" + out.getvalue()  # a byte-order mark, so spreadsheet programs read Hindi text correctly
