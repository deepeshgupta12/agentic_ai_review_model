"""Assembling the frozen page payload and its dependency manifest (Step 10.2-10.6; content.schema.json; D23, D28, D64).

Everything the public page shows is in the payload; everything it depends on is in the manifest, both hashed:
- reviews are the approved review revisions exactly as approved, in one balanced list (D69): positive, negative and
  mixed alternate in proportion, at most `PAGE_REVIEWS_MAX`; the page shows them as Person 1, Person 2, ... with no
  name, credit line or source line (the credit stays in the payload for moderators and withdrawal);
- blocks written from findings (overview, advantages, considerations, questions) come from the editor and cite exact
  finding and claim revisions; a page built from reviews alone has no overview and no such blocks (D64);
- "sources behind the findings" are the sources of the cited claims' supporting evidence whose current policy allows
  derived publication;
- heading and metadata name the project for search ("<name> Reviews: What Buyers Say") and add no facts; a
  reviews-only page has no attribution or coverage line (D69);
- JSON-LD is built by the backend from the visible content (a WebPage about the project as a place); it never carries
  a rating, a review entity or an FAQ block (D66).
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from typing import Any
from urllib.parse import urlsplit

from pymongo.client_session import ClientSession
from pymongo.database import Database

from app.config import Settings
from app.content.hashing import nfc
from app.db import iso
from app.sources import policies

LOCALE = "en-IN"
TITLE_MAX, DESCRIPTION_MAX = 70, 170
PLATFORMS = {
    "youtube.com": "YouTube",
    "youtu.be": "YouTube",
    "instagram.com": "Instagram",
    "facebook.com": "Facebook",
    "reddit.com": "Reddit",
    "quora.com": "Quora",
    "x.com": "X",
    "twitter.com": "X",
    "magicbricks.com": "MagicBricks",
    "99acres.com": "99acres",
    "housing.com": "Housing.com",
    "nobroker.in": "NoBroker",
    "mouthshut.com": "MouthShut",
}
CREDIT_KIND = {"comment": "comment", "video": "video", "short": "video", "user_review": "review"}  # else "post"
ATTRIBUTION = "Compiled by the editorial team from public discussions; reviewed by our editorial team."
REVIEWS_ATTRIBUTION = None  # D69: no attribution line on a reviews-only page


def host_of(url: str | None) -> str:
    host = (urlsplit(url).hostname or "") if url else ""
    return host[4:] if host.startswith("www.") else host


def platform_name(url: str | None) -> str:
    host = host_of(url)
    for known, name in PLATFORMS.items():
        if host == known or host.endswith("." + known):
            if name == "Reddit":  # the subreddit is where it was said (r/gurgaon)
                parts = urlsplit(url or "").path.split("/")
                return f"Reddit, r/{parts[2]}" if len(parts) > 2 and parts[1] == "r" and parts[2] else name
            return name
    return host or "the web"


def balanced(reviews: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    """One list of at most `limit` reviews in which positive, negative and mixed alternate in proportion to how many
    there are (D69), each side newest first; nothing negative is pushed to the end."""
    sides: dict[str, list[dict[str, Any]]] = {}
    for review in reviews:
        sides.setdefault(review["polarity"], []).append(review)
    for side in sides.values():
        side.sort(key=lambda r: str((r.get("published") or {}).get("value") or ""), reverse=True)
    total = sum(len(s) for s in sides.values())
    shown = {k: 0 for k in sides}
    out: list[dict[str, Any]] = []
    while len(out) < min(limit, total):
        # the side furthest behind its share goes next, measured at the middle of its next place (Webster's rule), so a
        # side with a single review is placed in the middle of the list, not at its end
        key = min(
            (k for k in sides if shown[k] < len(sides[k])),
            key=lambda k: (shown[k] + 0.5) / len(sides[k]),
        )
        out.append(sides[key][shown[key]])
        shown[key] += 1
    return out


def shorten(text: str, limit: int) -> str:
    """At most `limit` characters, cut at a word boundary (metadata only; never page prose)."""
    text = " ".join(text.split())
    if len(text) <= limit:
        return text
    cut = text[: limit - 1].rsplit(" ", 1)[0].rstrip(",;:")
    return cut + "…"


def _dated(value: dict[str, Any] | None) -> dict[str, Any]:
    if not value or value.get("status") == "unknown" or value.get("value") is None:
        return {"status": "unknown", "value": None, "precision": None, "basis": None}
    out = dict(value)
    out["value"] = iso(value["value"]) if isinstance(value["value"], datetime) else value["value"]
    return out


def _source(db: Database[dict[str, Any]], ref: dict[str, Any], session: ClientSession | None) -> dict[str, Any]:
    source = db["ai_sources"].find_one({"_id": f"{ref['id']}@{ref['revision']}"}, session=session)
    if source is None:
        raise LookupError(f"source {ref['id']} revision {ref['revision']} is missing")
    return source


def public_review(
    db: Database[dict[str, Any]], review: dict[str, Any], session: ClientSession | None
) -> dict[str, Any]:
    """PublicReview: the approved words with their credit line (D28)."""
    source = _source(db, review["source"], session)
    return {
        "text": review["text"],
        "polarity": review["polarity"],
        "aspects": review["aspects"],
        "credit": {
            "speaker_label": review["speaker_label"],
            "platform": platform_name(source.get("canonical_url")),
            "kind": CREDIT_KIND.get(review["source_kind"], "post"),
            "published": _dated(review["published"]),
            "timestamp_ms": review["timestamp_ms"] if review["source_kind"] in ("video", "short") else None,
            "translated_from": review["original_language"] if review["rendering"] == "translated" else None,
        },
        "source_url": None,  # show_review_source_links is off (D28); links stay internal for moderators
        "support": {
            "review": {"id": review["id"], "revision": review["revision"]},
            "source": {"id": review["source"]["id"], "revision": review["source"]["revision"]},
            "evidence": [{"id": e["id"], "revision": e["revision"]} for e in review["evidence"]],
        },
    }


def claims_of(
    db: Database[dict[str, Any]], findings: list[dict[str, Any]], session: ClientSession | None = None
) -> list[dict[str, Any]]:
    seen: dict[tuple[str, int], dict[str, Any]] = {}
    for finding in findings:
        for ref in finding["claims"]:
            key = (ref["id"], ref["revision"])
            if key not in seen:
                claim = db["ai_claims"].find_one({"id": ref["id"], "revision": ref["revision"]}, session=session)
                if claim is None:
                    raise LookupError(f"claim {ref['id']} revision {ref['revision']} is missing")
                seen[key] = claim
    return list(seen.values())


def _evidence(
    db: Database[dict[str, Any]], refs: list[dict[str, Any]], session: ClientSession | None
) -> list[dict[str, Any]]:
    out = []
    for ref in sorted({(r["id"], r["revision"]) for r in refs}):
        evidence = db["ai_evidence"].find_one({"id": ref[0], "revision": ref[1]}, session=session)
        if evidence is None:
            raise LookupError(f"evidence {ref[0]} revision {ref[1]} is missing")
        out.append(evidence)
    return out


def source_links(
    db: Database[dict[str, Any]], claims: list[dict[str, Any]], session: ClientSession | None = None
) -> list[dict[str, Any]]:
    """Sources behind the findings: one entry per source revision, if its current policy allows derived
    publication; the earliest cited video moment for a video."""
    spans = _evidence(db, [e for c in claims for e in c["supporting_evidence"]], session)
    links: dict[tuple[str, int], dict[str, Any]] = {}
    for span in spans:
        key = (span["source"]["id"], span["source"]["revision"])
        source = _source(db, span["source"], session)
        policy = policies.current(db, source["policy"]["family"], session=session)
        if policy is None or not policy["derived_publication_allowed"] or not source.get("canonical_url"):
            continue
        start = span["anchor"].get("start_ms") if span["anchor"].get("kind") == "time" else None
        if key in links:
            earlier = links[key]["timestamp_ms"]
            if start is not None and (earlier is None or start < earlier):
                links[key]["timestamp_ms"] = start
            continue
        links[key] = {
            "source": {"id": key[0], "revision": key[1]},
            "title": " ".join((source.get("title") or platform_name(source["canonical_url"])).split())[:200],
            "url": source["canonical_url"],
            "platform": platform_name(source["canonical_url"]),
            "published": _dated(source.get("publication_date")),
            "timestamp_ms": start,
        }
    return [links[k] for k in sorted(links)]


def manifest_for(
    db: Database[dict[str, Any]],
    findings: list[dict[str, Any]],
    reviews: list[dict[str, Any]],
    epoch: int,
    session: ClientSession | None = None,
) -> dict[str, Any]:
    """Exact dependencies, sorted and unique (DependencyManifest)."""
    claims = claims_of(db, findings, session)
    refs = [e for c in claims for e in c["supporting_evidence"] + c["contradicting_evidence"]]
    refs += [e for r in reviews for e in r["evidence"]]
    spans = _evidence(db, refs, session)
    pair = lambda x: {"id": x["id"], "revision": x["revision"]}  # noqa: E731
    by = lambda x: (x["id"], x["revision"])  # noqa: E731
    sources = {(s["source"]["id"], s["source"]["revision"]) for s in spans}
    sources |= {(r["source"]["id"], r["source"]["revision"]) for r in reviews}
    return {
        "findings": sorted((pair(f) for f in findings), key=by),
        "claims": sorted((pair(c) for c in claims), key=by),
        "reviews": sorted((pair(r) for r in reviews), key=by),
        "evidence": sorted((pair(s) for s in spans), key=by),
        "sources": [{"id": i, "revision": r} for i, r in sorted(sources)],
        "links": sorted({s["link_id"] for s in spans} | {r["link_id"] for r in reviews}),
        "policies": [
            {"family": f, "policy_version": v}
            for f, v in sorted({(s["policy"]["family"], s["policy"]["policy_version"]) for s in spans})
        ],
        "eligibility_epoch": epoch,
    }


def evidence_window(
    db: Database[dict[str, Any]], manifest: dict[str, Any], today: date, session: ClientSession | None = None
) -> dict[str, str]:
    """From the earliest to the latest known source date; today when no source has a known date."""
    days = []
    for ref in manifest["sources"]:
        value = (_source(db, ref, session).get("publication_date") or {}).get("value")
        if isinstance(value, datetime):
            days.append(value.astimezone(UTC).date())
    if not days:
        return {"from": today.isoformat(), "to": today.isoformat()}
    return {"from": min(days).isoformat(), "to": max(days).isoformat()}


def default_heading(project: dict[str, Any]) -> str:
    return f"{project['project_name']} Reviews: What Buyers Say"


def default_metadata(project: dict[str, Any], reviews: int, findings: int) -> dict[str, str]:
    """Search title and description that name the project and its place (D69: no site name in the reviews)."""
    name, where = project["project_name"], f"{project['locality']}, {project['city']}"
    title = shorten(f"{name} Reviews, {where}: What Buyers Say", TITLE_MAX)
    counted = f"{reviews} {'review' if reviews == 1 else 'reviews'}"
    if findings:
        description = f"{name}, {where}: what buyers like and what concerns them, from {counted} and public discussion."
    else:
        description = f"Read {counted} of {name}, {where}: what owners and buyers like and what concerns them."
    return {"title": title, "description": shorten(description, DESCRIPTION_MAX)}


def default_coverage_note(reviews: list[dict[str, Any]], public: list[dict[str, Any]], findings: int) -> str:
    """What the page rests on. A reviews-only page does not show it (D69); it stays in the payload for moderators."""
    sides = {k: sum(1 for r in public if r["polarity"] == k) for k in ("positive", "negative", "mixed")}
    note = f"{len(public)} {'review' if len(public) == 1 else 'reviews'}: " + ", ".join(
        f"{count} {side}" for side, count in sides.items() if count
    )
    if findings:
        note += f"; {findings} {'point' if findings == 1 else 'points'} drawn from public discussion"
    return note + "."


def json_ld(project: dict[str, Any], heading: str, metadata: dict[str, Any], reviewed_on: str) -> dict[str, Any]:
    """Self-contained WebPage entity about the project as a place (docs/08 SEO/AEO). No rating, review or FAQ
    entity (D66); a later PDP integration can merge `about` into its own entity graph."""
    address = {"@type": "PostalAddress", "addressLocality": project["locality"], "addressCountry": "IN"}
    address["addressRegion"] = project.get("state") or project["city"]
    return {
        "@context": "https://schema.org",
        "@type": "WebPage",
        "name": heading,
        "description": metadata["description"],
        "url": metadata["canonical_path"],
        "inLanguage": LOCALE,
        "dateModified": reviewed_on,
        "about": {"@type": "Place", "name": project["project_name"], "address": address},
        "publisher": {"@type": "Organization", "name": "Project Intelligence"},
    }


def robots(settings: Settings) -> str:
    items = json.loads((settings.seed_dir / "operating_defaults.json").read_text(encoding="utf-8"))["items"]
    indexing = items.get("public_page_indexing", {}).get("value")
    return "index" if indexing in (True, "index") else "noindex"


def assemble(
    *,
    project: dict[str, Any],
    settings: Settings,
    reviews: list[dict[str, Any]],
    public_reviews: list[dict[str, Any]],
    findings_count: int,
    blocks: dict[str, Any],
    sources: list[dict[str, Any]],
    window: dict[str, str],
    today: date,
    metadata: dict[str, str] | None = None,
) -> dict[str, Any]:
    """The full ContentPayload. `blocks` holds heading, overview (or None), advantages, considerations, questions and
    coverage_note (each may be absent: deterministic defaults are used)."""
    meta = metadata or default_metadata(project, len(reviews), findings_count)
    heading = blocks.get("heading") or default_heading(project)
    full_meta = {
        "title": shorten(meta["title"], TITLE_MAX),
        "description": shorten(meta["description"], DESCRIPTION_MAX),
        "canonical_path": f"/projects/{project['slug']}",
        "robots": robots(settings),
    }
    reviewed_on = today.isoformat()
    payload = {
        "payload_schema": "content-payload/1",
        "project": {"id": project["_id"], "slug": project["slug"], "name": project["project_name"]},
        "locale": LOCALE,
        "evidence_window": window,
        "heading": heading,
        "overview": blocks.get("overview"),
        "advantages": blocks.get("advantages", []),
        "considerations": blocks.get("considerations", []),
        "reviews": public_reviews,
        "questions": blocks.get("questions", []),
        "sources": sources,
        "coverage_note": blocks.get("coverage_note") or default_coverage_note(reviews, public_reviews, findings_count),
        "reviewed_on": reviewed_on,
        "attribution": ATTRIBUTION if findings_count else REVIEWS_ATTRIBUTION,
        "metadata": full_meta,
        "json_ld": json_ld(project, heading, full_meta, reviewed_on),
    }
    return nfc(payload)
