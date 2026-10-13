"""RERA registries of the other states (Step 08; D57, D61): the registration record of each supplied RERA number.

Each state runs its own portal, and few of them offer a page a reader can reach from the registration number alone.
What they have in common is the registration certificate (often a PDF with a text layer) and project pages that
search engines index. So, per RERA number:
1. candidates: the portal's own address for the number where one exists (Karnataka), otherwise a Brave search for
   the quoted number restricted to the state portal's domains (checked 13 Oct 2026: it finds UP RERA certificates);
2. each candidate is read under the official_records policy (robots.txt recorded, D46/D61; a refused page is asked
   for once more through Scrapfly, D61), as HTML or PDF;
3. the page is kept only if it states the number itself, so a page about another registration is never stored;
4. only registry facts are kept: a certificate up to its conditions section, an HTML page only its labelled registry
   lines; telephone numbers, e-mail addresses and identity numbers are removed (directors' details are personal).
A number not found is reported by name in the run's coverage. States without a configured portal stay
access_pending (app.connectors.registries).
"""

from __future__ import annotations

import io
import re
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote

from pymongo.database import Database

from app.connectors.base import Connector, ProviderError, QuotaExhausted
from app.connectors.web import extract
from app.sources import policies
from app.sources.http import FetchError, SafeClient
from app.sources.robots import RobotsCache
from app.sources.state import log_fetch
from app.sources.store import Item, normalise_url

ID = "state_registry"
FAMILY = "official_records"
PDF_TYPES = ("application/pdf", "application/octet-stream")
PAGE_TYPES = ("text/html", "application/xhtml+xml", *PDF_TYPES)
MAX_RECORD_CHARS = 2500
CANDIDATES_PER_NUMBER = 3


@dataclass(frozen=True)
class Portal:
    name: str
    domains: tuple[str, ...]
    direct: str | None = None  # address template for a registration number, `{number}` URL-quoted


PORTALS: dict[str, Portal] = {
    "karnataka": Portal(
        "Karnataka RERA",
        ("rera.karnataka.gov.in",),
        "https://rera.karnataka.gov.in/certificate?CER_NO={number}",
    ),
    "uttar pradesh": Portal("UP RERA", ("up-rera.in",)),
    "maharashtra": Portal("MahaRERA", ("maharera.maharashtra.gov.in", "maharera.mahaonline.gov.in")),
    "telangana": Portal("TS RERA", ("rerait.telangana.gov.in",)),
    "tamil nadu": Portal("TN RERA", ("rera.tn.gov.in",)),
    "gujarat": Portal("GujRERA", ("gujrera.gujarat.gov.in",)),
    "delhi": Portal("Delhi RERA", ("rera.delhi.gov.in",)),
    "punjab": Portal("Punjab RERA", ("rera.punjab.gov.in",)),
    "rajasthan": Portal("Rajasthan RERA", ("rera.rajasthan.gov.in",)),
    "madhya pradesh": Portal("MP RERA", ("rera.mp.gov.in",)),
    "kerala": Portal("K-RERA", ("rera.kerala.gov.in",)),
    "andhra pradesh": Portal("AP RERA", ("rera.ap.gov.in",)),
    "goa": Portal("Goa RERA", ("rera.goa.gov.in",)),
    "west bengal": Portal("WB RERA", ("rera.wb.gov.in",)),
    "bihar": Portal("Bihar RERA", ("rera.bihar.gov.in",)),
    "uttarakhand": Portal("Uttarakhand RERA", ("ukrera.uk.gov.in",)),
}
PORTAL_DOMAINS = sorted({d for p in PORTALS.values() for d in p.domains})

FACT_LABEL = re.compile(
    r"^\s*(?:\d+[.)]\s*)?(registration (?:no|number|certificate)|project (?:registration )?(?:no|number|name|"
    r"address|status|type|approval date)|name of (?:the )?(?:project|promoter)|promoter(?: name| type)?|"
    r"(?:date of )?registration date|date of (?:registration|issue|approval)|"
    r"(?:proposed|revised|original|actual) (?:date of )?completion|"
    r"completion date|valid(?:ity)?(?: up ?to| till| from)?|(?:village|locality|sector|tehsil|district|taluk|state|"
    r"pin ?code)(?:/[a-z ]+)*|occupancy|completion certificate|number of (?:units|apartments|plots|towers|buildings)|"
    r"total (?:area|units)|land area)\b",
    re.IGNORECASE,
)
CERTIFICATE = re.compile(
    r"registration certificate|certificate of registration|form[\s-]*['\"]?c['\"]?\b|project registration number|"
    r"registration (?:no|number)\s*[:.-]|project approval date|real estate regulatory authority",
    re.IGNORECASE,
)
PROCEEDINGS = re.compile(r"cause list|appeal no|complainant|respondent|appellant|advocate|hearing", re.IGNORECASE)
CONDITIONS = re.compile(
    r"\n\s*(?:1\.\s*)?This registration is granted subject to|\n\s*Conditions? of registration", re.I
)
PHONE = re.compile(r"(?<!\d)(?:\+?91[\s-]?)?[6-9]\d{4}[\s-]?\d{5}(?!\d)|(?<!\d)0\d{2,4}[\s-]\d{6,8}(?!\d)")
EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")
IDENTITY = re.compile(r"\b[A-Z]{5}\d{4}[A-Z]\b|(?<!\d)\d{4}\s\d{4}\s\d{4}(?!\d)")  # PAN, Aadhaar


def squash(text: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", text.upper())


def redact(text: str) -> str:
    return IDENTITY.sub("[removed]", EMAIL.sub("[removed]", PHONE.sub("[removed]", text)))


def pdf_text(body: bytes) -> str:
    from pypdf import PdfReader  # BSD licence; certificate PDFs only

    try:
        reader = PdfReader(io.BytesIO(body))
        return "\n".join((page.extract_text() or "") for page in reader.pages[:3])
    except Exception:  # a malformed PDF is a page we cannot read, not a failure of the run
        return ""


def registry_facts(text: str, is_pdf: bool) -> str:
    """The registry facts of a record: a certificate up to its conditions; an HTML page's labelled lines only."""
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in text.splitlines()]
    if is_pdf:
        cut = CONDITIONS.search(text)
        kept = "\n".join(line for line in (text[: cut.start()] if cut else text).splitlines() if line.strip())
    else:
        kept = "\n".join(line for line in lines if line and FACT_LABEL.match(line))
    return redact(kept)[:MAX_RECORD_CHARS].strip()


class StateRegistry(Connector):
    id = ID
    supports = frozenset({"fetch_item", "health"})

    def __init__(
        self,
        client: SafeClient,
        robots: RobotsCache,
        db: Database[dict[str, Any]],
        brave: Connector | None,
        unblocker: Any = None,
    ) -> None:
        self.client, self.robots, self.db, self.brave, self.unblocker = client, robots, db, brave, unblocker

    def candidates(self, portal: Portal, number: str) -> list[str]:
        found: list[str] = []
        if portal.direct:
            found.append(portal.direct.format(number=quote(number, safe="")))
        if self.brave is not None:
            sites = " OR ".join(f"site:{d}" for d in portal.domains)
            query = {"query_text": f'"{number}" {sites}', "window_days": 3650, "exclusions": []}
            for hit in self.brave.discover(query, None).items:
                host = (hit.canonical_url.split("/")[2] if "//" in hit.canonical_url else "").lower()
                if any(host == d or host.endswith("." + d) for d in portal.domains):
                    found.append(hit.canonical_url)
        return list(dict.fromkeys(found))[:CANDIDATES_PER_NUMBER]

    def _get(self, url: str, run_id: str | None) -> tuple[bytes | str, bool] | None:
        """(body, is_pdf) of one candidate under the official_records policy, or None (logged)."""
        resolution = policies.resolve(self.db, url)
        entry: dict[str, Any] = {
            "connector_id": self.id,
            "url": url,
            "host": resolution.host,
            "family": resolution.family,
            "policy_version": resolution.policy["policy_version"] if resolution.policy else None,
            "robots": None,
            "status_code": None,
            "run_id": run_id,
        }
        if resolution.family != FAMILY or not resolution.may_collect:
            log_fetch(self.db, {**entry, "outcome": "not_allowed"})
            return None
        decision = self.robots.decide(url)
        entry["robots"] = decision.basis if decision.allowed else f"disallowed ({decision.basis})"
        if not decision.allowed and policies.obeys_robots(resolution.policy):
            log_fetch(self.db, {**entry, "outcome": "robots_disallowed"})
            return None
        try:
            response = self.client.get(url, accept=PAGE_TYPES)
        except FetchError as exc:
            log_fetch(self.db, {**entry, "outcome": f"error:{exc.code}", "status_code": exc.status})
            return None
        entry["status_code"] = response.status
        if response.status in (401, 403, 406, 451) and self.unblocker is not None:
            log_fetch(self.db, {**entry, "outcome": "refused"})
            try:
                page = self.unblocker.scrape(url)
            except (QuotaExhausted, ProviderError, FetchError) as exc:
                log_fetch(self.db, {**entry, "outcome": f"unblock_error:{getattr(exc, 'code', 'quota')}"})
                return None
            if page.upstream_status >= 400 or not page.html:
                log_fetch(self.db, {**entry, "outcome": "unblock_refused", "provider_credits": page.credits})
                return None
            log_fetch(self.db, {**entry, "outcome": "fetched_unblocked", "provider_credits": page.credits})
            return page.html, False
        if response.status >= 400:
            log_fetch(self.db, {**entry, "outcome": "refused" if response.status in (401, 403, 406, 451) else "error"})
            return None
        log_fetch(self.db, {**entry, "outcome": "fetched"})
        content_type = response.headers.get("content-type", "").split(";")[0].strip().lower()
        is_pdf = content_type in PDF_TYPES or response.body[:5] == b"%PDF-"
        return (response.body if is_pdf else response.text()), is_pdf

    @staticmethod
    def not_a_record(text: str, number: str, is_pdf: bool) -> str | None:
        """Why this page is not the number's registration record, or None."""
        if squash(number) not in squash(text):
            return "number_not_on_page"
        if PROCEEDINGS.search(text[:4000]):
            return "proceedings_not_a_record"
        if is_pdf and not CERTIFICATE.search(text):
            return "not_a_certificate"
        if not is_pdf and len(registry_facts(text, is_pdf=False).splitlines()) < 2:
            return "no_registry_facts"
        return None

    def record(self, state: str, number: str, run_id: str | None = None) -> Item | None:
        """The registration record of `number` on `state`'s portal, or None when no page states it."""
        portal = PORTALS[state]
        for url in self.candidates(portal, number):
            got = self._get(normalise_url(url), run_id)
            if got is None:
                continue
            body, is_pdf = got
            if is_pdf:
                assert isinstance(body, bytes)
                text = pdf_text(body)
            else:
                assert isinstance(body, str)
                text = (extract(body, url) or {}).get("text") or ""
            refusal = self.not_a_record(text, number, is_pdf)
            if refusal:
                entry = {"connector_id": self.id, "url": url, "host": url.split("/")[2], "run_id": run_id}
                log_fetch(self.db, {**entry, "outcome": refusal})
                continue
            facts = registry_facts(text, is_pdf)
            if squash(number) not in squash(facts):
                facts = f"Registration number: {number}\n{facts}".strip()
            body_text = (
                f"{portal.name} registration {number} ({state.title()}).\n{facts}\n"
                f"Source: the {portal.name} portal ({'registration certificate' if is_pdf else 'project page'})."
            )
            return Item(
                connector_id=self.id,
                native_id=f"{state}:{number}",
                canonical_url=normalise_url(url),
                source_kind="registration_record",
                capture_level="full_content",
                title=f"{portal.name} registration {number}",
                text=body_text,
                language="en",
            )
        return None

    def health(self) -> dict[str, Any]:
        return {"portals": len(PORTALS), "quota": None}
