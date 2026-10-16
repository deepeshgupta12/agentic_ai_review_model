"""Individual reviews from portal and forum pages (review-first fixes, 13 Oct 2026; D67, D68).

A portal page about a project (MagicBricks, 99acres, Housing.com, NoBroker) or a Quora question holds several
people's reviews or answers. Stored whole, they read as one article and no review can be credited to one person
(the Step 08 gap the product owner found). This module splits a fetched page into one record per review, using the
review data the site itself publishes, never a model:

- MagicBricks: the project reviews in the page's preloaded state (`projectPageSeoStaticData.projectReviews`), with
  the reviewer's type and relation ("Owner", "Lives in Project", "Agent in Project"), date and title. Locality
  reviews on the same page are not about the project and are not read.
- 99acres: schema.org `Review` items; the project page labels the locality's reviews as the project's in its
  markup, so a review whose words are among the page's locality reviews is kept titled as the locality's (D73).
- NoBroker forum pages: the answers (`Comment`) of the `DiscussionForumPosting`; the question text is NoBroker's own
  summary and is left out.
- Quora (D67): the answers in the page's `QAPage` markup, which is what a signed-out visitor is served.
- Any other page (Housing.com and others): schema.org `Review` items whose reviewed item, when named, is the project.

Reviews written by agents or dealers are kept with their badge (role broker), and 99acres' locality reviews with a
title saying so, for the moderator to decide (D73). Left out and counted: reviews marked sponsored, empty or very
short texts, and duplicates. Reviewer names are never kept: only the role the platform's badge states (owner,
resident, broker), or unknown.
"""

from __future__ import annotations

import hashlib
import html as html_lib
import json
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlsplit

from app.sources.store import Item

MIN_WORDS = 5
MAX_CHARS = 3000
LD_JSON = re.compile(r"<script[^>]*application/ld\+json[^>]*>(.*?)</script>", re.S | re.I)
MB_STATE = re.compile(r"window\.SERVER_PRELOADED_STATE_\s*=\s*")
NN_STATE = re.compile(r"window\.__initialData__\s*=\s*")
TAG = re.compile(r"<[^>]+>")
UNKNOWN = {"status": "unknown", "value": None, "precision": None, "basis": None}


@dataclass
class PageReview:
    key: str  # stable within the page: the platform's review ID, or a digest of the words
    text: str
    title: str | None
    role: str  # SourceRole: owner, resident, broker or unknown
    role_basis: str  # platform_badge or none
    published: dict[str, Any]
    kind: str  # user_review (portal) or forum_post (forum answer)


@dataclass
class PageReviews:
    reviews: list[PageReview] = field(default_factory=list)
    dropped: dict[str, int] = field(default_factory=dict)
    more_url: str | None = None  # the portal's full review page, when the project page lists only some

    def drop(self, reason: str) -> None:
        self.dropped[reason] = self.dropped.get(reason, 0) + 1


def host_of(url: str) -> str:
    host = (urlsplit(url).hostname or "").lower()
    return host[4:] if host.startswith("www.") else host


def clean(value: Any) -> str:
    """Plain text: tags removed, entities decoded, whitespace collapsed."""
    text = html_lib.unescape(TAG.sub(" ", str(value or "")))
    return " ".join(text.split())[:MAX_CHARS]


def _digest(text: str) -> str:
    return hashlib.sha256(" ".join(text.lower().split()).encode()).hexdigest()[:16]


def _json_after(page: str, marker: re.Pattern[str]) -> Any:
    match = marker.search(page)
    if not match:
        return None
    try:
        value, _ = json.JSONDecoder().raw_decode(page[match.end() :])
    except ValueError:
        return None
    return value


def ld_items(page: str) -> list[dict[str, Any]]:
    """Every object in the page's JSON-LD blocks, nested ones included."""
    out: list[dict[str, Any]] = []

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            out.append(node)
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    for block in LD_JSON.findall(page):
        try:
            walk(json.loads(block))
        except ValueError:
            continue
    return out


def _types(item: dict[str, Any]) -> set[str]:
    kind = item.get("@type")
    return set(kind) if isinstance(kind, list) else {str(kind)}


def dated(value: Any, now: datetime | None = None) -> dict[str, Any]:
    """DatedValue from what a platform states: ISO times, dd/mm/yyyy days, or '5Y ago' (approximate)."""
    text = str(value or "").strip()
    if not text:
        return dict(UNKNOWN)
    match = re.fullmatch(r"(\d{1,2})/(\d{1,2})/(\d{4})", text)
    if match:
        day, month, year = (int(x) for x in match.groups())
        try:
            return {
                "status": "known",
                "value": datetime(year, month, day, tzinfo=UTC).isoformat().replace("+00:00", "Z"),
                "precision": "day",
                "basis": "platform_metadata",
            }
        except ValueError:
            return dict(UNKNOWN)
    match = re.fullmatch(r"(\d+)\s*([YMD])\s*ago", text, re.I)
    if match:
        count, unit = int(match.group(1)), match.group(2).upper()
        days = {"Y": 365, "M": 30, "D": 1}[unit] * count
        when = (now or datetime.now(UTC)) - timedelta(days=days)
        precision = {"Y": "year", "M": "month", "D": "day"}[unit]
        return {
            "status": "approximate",
            "value": when.replace(hour=0, minute=0, second=0, microsecond=0).isoformat().replace("+00:00", "Z"),
            "precision": precision,
            "basis": "platform_metadata",
        }
    try:
        when = datetime.fromisoformat(text.replace("Z", "+00:00").replace(" ", "T", 1))
    except ValueError:
        return dict(UNKNOWN)
    if when.tzinfo is None:
        when = when.replace(tzinfo=UTC)
    instant = "T" in text or " " in text
    return {
        "status": "known",
        "value": when.astimezone(UTC).isoformat().replace("+00:00", "Z"),
        "precision": "instant" if instant else "day",
        "basis": "platform_metadata",
    }


def _keep(out: PageReviews, seen: set[str], review: PageReview) -> None:
    if not review.text:
        out.drop("empty")
        return
    if len(review.text.split()) < MIN_WORDS:
        out.drop("too_short")
        return
    digest = _digest(review.text)
    if digest in seen:
        out.drop("duplicate")
        return
    seen.add(digest)
    out.reviews.append(review)


# --- MagicBricks -------------------------------------------------------------------------------------------------


def _magicbricks_role(user_type: str, relation: str) -> tuple[str, str]:
    t, r = user_type.lower(), relation.lower()
    if "agent" in t or "agent" in r or "broker" in t or "builder" in t or "developer" in t:
        return "broker", "platform_badge"
    if "lives" in r or "tenant" in t or "tenant" in r or "resident" in r:
        return "resident", "platform_badge"
    if "owner" in t or "owner" in r:
        return "owner", "platform_badge"
    return "unknown", "none"


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def magicbricks(page: str, url: str = "") -> PageReviews:
    out = PageReviews()
    state = _json_after(page, MB_STATE)
    if not isinstance(state, dict):
        return out
    block = _dict(_dict(state.get("projectPageSeoStaticData")).get("projectReviews"))
    seen: set[str] = set()
    listed = block.get("resultList")
    listed = [i for i in listed if isinstance(i, dict)] if isinstance(listed, list) else []
    for item in listed:
        role, basis = _magicbricks_role(str(item.get("userType") or ""), str(item.get("userRelation") or ""))
        if str(item.get("isSponsered") or item.get("isSponsored") or "").lower() == "true":
            out.drop("sponsored")
            continue
        _keep(
            out,
            seen,
            PageReview(
                key=f"mb-{item.get('reviewId') or _digest(clean(item.get('reviewDescription')))}",
                text=clean(item.get("reviewDescription")),
                title=clean(item.get("reviewTitle")) or None,
                role=role,
                role_basis=basis,
                published=dated(item.get("reviewedOn") or item.get("postedOn")),
                kind="user_review",
            ),
        )
    try:
        total = int(float(block.get("count") or 0))
    except (TypeError, ValueError):
        total = 0
    if total > len(listed):
        # the full review list of THIS project (its own pdpid), never another project's from a "similar projects" block
        own = re.search(r"pdpid-([0-9a-f]+)", url)
        pdpid = own.group(1) if own else "[0-9a-f]+"
        found = re.search(rf"https://www\.magicbricks\.com/[a-z0-9-]+-reviews-[a-z0-9-]*pdpid-{pdpid}\b", page)
        out.more_url = found.group(0) if found and found.group(0) != url else None
    return out


# --- 99acres -----------------------------------------------------------------------------------------------------


def _locality_texts(state: Any) -> set[str]:
    """Digests of every text under a key naming locality reviews (the page's own label for them)."""
    found: set[str] = set()

    def collect(node: Any) -> None:
        if isinstance(node, dict):
            for value in node.values():
                collect(value)
        elif isinstance(node, list):
            for value in node:
                collect(value)
        elif isinstance(node, str) and len(node.split()) >= MIN_WORDS:
            found.add(_digest(clean(node)))

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                if "localityreview" in key.lower().replace("_", ""):
                    collect(value)
                else:
                    walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk(state)
    return found


def _role_from_name(name: str) -> tuple[str, str]:
    """The role a badge in the author field states ("Owner", "Tenant", "Agent"); whole words only, so a person's
    name that merely contains one ("Sagenta") states nothing."""
    words = set(re.findall(r"[a-z]+", name.lower()))
    if "owner" in words:
        return "owner", "platform_badge"
    if words & {"tenant", "resident"}:
        return "resident", "platform_badge"
    if words & {"agent", "broker", "builder", "dealer"}:
        return "broker", "platform_badge"
    return "unknown", "none"


LOCALITY_TITLE = "A review of the locality, shown on the project's page"


def ninety_nine_acres(page: str) -> PageReviews:
    """The page's reviews. It marks up its locality's reviews as the project's: they are kept too, titled as the
    locality's, for the moderator to decide (D73); without the page state they cannot be told apart and are kept
    untitled."""
    out = PageReviews()
    state = _json_after(page, NN_STATE)
    locality = _locality_texts(state) if state is not None else set()
    seen: set[str] = set()
    for item in ld_items(page):
        if "Review" not in _types(item) or not item.get("reviewBody"):
            continue
        text = clean(item.get("reviewBody"))
        title = LOCALITY_TITLE if _digest(text) in locality else None
        role, basis = _role_from_name(
            clean((item.get("author") or {}).get("name") if isinstance(item.get("author"), dict) else "")
        )
        _keep(
            out,
            seen,
            PageReview(
                f"nn-{_digest(text)}", text, title, role, basis, dated(item.get("datePublished")), "user_review"
            ),
        )
    return out


# --- NoBroker forum, Quora and other schema.org markup ------------------------------------------------------------


def nobroker(page: str) -> PageReviews:
    out = PageReviews()
    seen: set[str] = set()
    postings = [i for i in ld_items(page) if "DiscussionForumPosting" in _types(i)]
    for posting in postings:
        comments = posting.get("comment") or []
        for item in comments if isinstance(comments, list) else [comments]:
            if not isinstance(item, dict):
                continue
            text = clean(item.get("text"))
            _keep(
                out,
                seen,
                PageReview(
                    f"nb-{_digest(text)}",
                    text,
                    None,
                    "unknown",
                    "none",
                    dated(item.get("datePublished") or item.get("dateCreated")),
                    "forum_post",
                ),
            )
    return out if postings else generic(page, [])


def quora(page: str) -> PageReviews:
    out = PageReviews()
    seen: set[str] = set()
    for item in ld_items(page):
        if "Answer" not in _types(item):
            continue
        text = clean(item.get("text"))
        _keep(
            out,
            seen,
            PageReview(
                f"qa-{_digest(text)}",
                text,
                None,
                "unknown",
                "none",
                dated(item.get("dateCreated") or item.get("datePublished")),
                "forum_post",
            ),
        )
    return out


def _names_match(name: str, project_names: list[str]) -> bool:
    folded = " ".join(re.findall(r"[a-z0-9]+", name.lower()))
    return any(" ".join(re.findall(r"[a-z0-9]+", n.lower())) in folded for n in project_names if n)


def generic(page: str, project_names: list[str]) -> PageReviews:
    out = PageReviews()
    seen: set[str] = set()
    for item in ld_items(page):
        if "Review" not in _types(item) or not item.get("reviewBody"):
            continue
        reviewed = item.get("itemReviewed")
        name = clean(reviewed.get("name")) if isinstance(reviewed, dict) else ""
        if name and project_names and not _names_match(name, project_names):
            out.drop("about_another_item")
            continue
        text = clean(item.get("reviewBody"))
        author = item.get("author")
        role, basis = _role_from_name(clean(author.get("name")) if isinstance(author, dict) else "")
        _keep(
            out,
            seen,
            PageReview(f"ld-{_digest(text)}", text, None, role, basis, dated(item.get("datePublished")), "user_review"),
        )
    return out


def review_key(native_id: str) -> str | None:
    """The review key of a source split from a page (`<site>#review-<key>`), or None for any other source."""
    return native_id.split("#review-", 1)[1] if "#review-" in native_id else None


def review_item(page: dict[str, Any], review: PageReview) -> Item:
    """One person's review on a portal or forum page, stored as its own source under the page (D68). The reviewer's
    name is never kept; only the role the platform's badge states. The review is known by its site and its key (the
    platform's review ID, or a digest of its words), not by the page: a portal shows the same review on the project
    page and on its full review list, and it is stored once."""
    return Item(
        connector_id=page["connector_id"],
        native_id=f"{host_of(page['canonical_url'])}#review-{review.key}",
        canonical_url=page["canonical_url"],
        source_kind=review.kind,
        capture_level="full_content",
        title=review.title,
        text=review.text,
        publication_date=review.published,
        language=None,
        author={"display_name": None, "role": review.role, "role_basis": review.role_basis},
        parent={"id": page["id"], "revision": page["revision"]},
    )


# Portal pages that never hold anyone's review (D72, D75): one flat for sale or rent (99acres "-spid-", MagicBricks
# "propertyDetails", Housing.com resale and rent listings) and a project's sub-pages (amenities, floor plans, location,
# photos, brochure, price trends, directions). On 15 Oct 2026, 34 of the 80 pages read for DLF Privana were such
# sub-pages while 14 pages naming the project went unread.
LISTING_PAGES = re.compile(
    r"99acres\.com/[^?#]*-spid-"
    r"|magicbricks\.com/propertydetails/"
    r"|magicbricks\.com/[^?#]*-(amenities|floor-plan|location|photo-videos|video-review|price-trends)-"
    r"|magicbricks\.com/[^?#]*-in-gurgaon-overview"
    r"|housing\.com/in/(buy|rent)/(resale|rent)/"
    r"|housing\.com/in/buy/projects/page/[^?#]*/(brochure|floor-plan|directions|amenities|price-trends)"
    r"|nobroker\.in/[^?#]*-prjt-[^?#]*/(amenities|location|floor-plan|price-trends|specifications)",
    re.IGNORECASE,
)


def listing_page(url: str) -> bool:
    """A portal page with no review on it: not worth one of the run's reads."""
    return bool(LISTING_PAGES.search(url))


def page_reviews(url: str, page: str, project_names: list[str]) -> PageReviews:
    """The individual reviews on a fetched page, by the site that published it."""
    host = host_of(url)
    if host.endswith("magicbricks.com"):
        return magicbricks(page, url)
    if host.endswith("99acres.com"):
        return ninety_nine_acres(page)
    if host.endswith("nobroker.in"):
        return nobroker(page)
    if host.endswith("quora.com"):
        return quora(page)
    return generic(page, project_names)
