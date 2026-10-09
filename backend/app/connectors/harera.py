"""HRERA registry reader (Step 08.4; connector `harera_registry`, policy family `official_records`; D53, D54).

Dated primary records for fact verification. The Haryana RERA public list of registered projects (one page per
district, no sign-in) has one row per registration: the certificate number and its date, the project ID, the
registered name, the promoter, the location, the district, the authority, the date the registration is valid up to,
and links to the certificate, quarterly progress reports and any occupation, completion or part-completion
certificate. One registry record is stored per RERA ID, built only from those facts and the date it was read.

Not read: the project preview page. Besides the project it repeats the promoter's earlier projects with their own
completion dates, which a loose reader confuses (seen on 9 Oct 2026), and it holds directors' personal addresses
and telephone numbers. The registration's validity date is a registry fact about the registration, never a
possession date; the verifier says so.

Fetches go through the same policy, robots.txt and fetch-log path as the web reader. A refused or missing page is
recorded and not worked around.
"""

from __future__ import annotations

import html as html_lib
import re
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any

from pymongo.database import Database

from app.connectors.base import Availability, Connector
from app.seed.normalise import normalise_rera_id
from app.sources import policies
from app.sources.http import FetchError, SafeClient
from app.sources.robots import RobotsCache
from app.sources.state import log_fetch
from app.sources.store import Item

ID = "harera_registry"
LISTINGS = {"gurugram": "https://haryanarera.gov.in/admincontrol/registered_projects/2"}
PREVIEW = "https://haryanarera.gov.in/view_project/project_preview_open/{}"
MAX_LISTING_BYTES = 12_000_000  # the Gurugram list was 2.6 MB on 9 Oct 2026 and grows with every registration
CERT = re.compile(r"[A-Z]{3}\s*/\s*\d{1,5}\s*/\s*\d{1,5}\s*/\s*\d{4}\s*/\s*\d{1,5}", re.IGNORECASE)  # as in identity
DATED = re.compile(r"DATED\s+(\d{1,2})[./-](\d{1,2})[./-](\d{4})", re.IGNORECASE)
SUPERSEDES = re.compile(r"SUPERSEDES\s+([A-Z]+\s*/[\d/\s]+)", re.IGNORECASE)
DAY = re.compile(r"^(\d{1,2})[./-](\d{1,2})[./-](\d{4})$")


@dataclass
class Registration:
    rera_id: str
    dated: date | None
    supersedes: str | None
    project_code: str
    name: str
    promoter: str
    location: str
    district: str
    registered_with: str
    valid_upto: date | None
    completion_certificate_listed: bool
    preview_id: str | None

    def text(self) -> str:
        """The stored record: registry facts only. When they were read is the source revision's collection time,
        so reading the same facts again is not a change."""
        valid = self.valid_upto.strftime("%d %B %Y") if self.valid_upto else "not stated"
        dated = self.dated.strftime("%d %B %Y") if self.dated else "not stated"
        lines = [
            f"Haryana RERA registration {self.rera_id}, dated {dated}.",
            f"Project ID: {self.project_code}.",
            f"Registered name: {self.name}.",
            f"Promoter: {self.promoter}.",
            f"Location: {self.location}, {self.district}.",
            f"Registered with: {self.registered_with}.",
            f"Registration valid up to: {valid}.",
            "Occupation, completion or part-completion certificate on the registry list: "
            + ("listed." if self.completion_certificate_listed else "none listed."),
        ]
        if self.supersedes:
            lines.insert(1, f"This registration supersedes {self.supersedes}.")
        lines.append("Source: the Haryana RERA public list of registered projects.")
        return "\n".join(lines)


def _cell_text(cell: str) -> str:
    return re.sub(r"\s+", " ", html_lib.unescape(re.sub(r"<[^>]+>", " ", cell))).strip()


def _day(value: str) -> date | None:
    m = DAY.match(value.strip())
    if not m:
        return None
    try:
        return date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
    except ValueError:
        return None


def normalise_cert(match: re.Match[str]) -> str:
    """The same form as the catalogue's `id_normalised`, so registrations compare exactly."""
    return normalise_rera_id(re.sub(r"\s+", "", match.group(0)))


def parse_listing(page: str) -> dict[str, Registration]:
    """Registrations by RERA ID from the list of registered projects. Columns are found by their headers, so a
    reordered table is read correctly and a changed one fails loudly (no registrations) instead of misreading."""
    found: dict[str, Registration] = {}
    for table in re.findall(r"<table.*?</table>", page, re.S | re.IGNORECASE):
        headers = [_cell_text(h) for h in re.findall(r"<th[^>]*>(.*?)</th>", table, re.S | re.IGNORECASE)]
        wanted = ("Registration Certificate Number", "Project ID", "Project Name", "Builder", "Registration Up-to")
        if not all(w in headers for w in wanted):
            continue
        col = {h: i for i, h in enumerate(headers)}
        for row in re.findall(r"<tr.*?</tr>", table, re.S | re.IGNORECASE):
            cells = re.findall(r"<td[^>]*>(.*?)</td>", row, re.S | re.IGNORECASE)
            if len(cells) < len(headers) - 1:
                continue
            texts = [_cell_text(c) for c in cells]
            cert_text = texts[col["Registration Certificate Number"]]
            cert = CERT.search(cert_text)
            if not cert:
                continue
            dated = DATED.search(cert_text)
            supersedes = SUPERSEDES.search(cert_text)
            oc_col = next((i for h, i in col.items() if h.startswith("View OC")), None)
            preview = re.search(r"project_preview_open/(\d+)", row)
            rera_id = normalise_cert(cert)
            found[rera_id] = Registration(
                rera_id=rera_id,
                dated=date(int(dated.group(3)), int(dated.group(2)), int(dated.group(1))) if dated else None,
                supersedes=re.sub(r"\s+", "", supersedes.group(1)) if supersedes else None,
                project_code=texts[col["Project ID"]],
                name=texts[col["Project Name"]],
                promoter=texts[col["Builder"]],
                location=texts[col["Project Location"]] if "Project Location" in col else "",
                district=texts[col["Project District"]] if "Project District" in col else "",
                registered_with=texts[col["Registered With"]] if "Registered With" in col else "",
                valid_upto=_day(texts[col["Registration Up-to"]]),
                completion_certificate_listed=bool(oc_col is not None and "<a" in cells[oc_col].lower()),
                preview_id=preview.group(1) if preview else None,
            )
    return found


class HareraRegistry(Connector):
    id = ID
    supports = frozenset({"fetch_item", "check_availability", "health"})

    def __init__(self, client: SafeClient, robots: RobotsCache, db: Database[dict[str, Any]]) -> None:
        self.client, self.robots, self.db = client, robots, db
        self._listing: dict[str, dict[str, Registration]] = {}

    def listing(self, district: str = "gurugram", run_id: str | None = None) -> dict[str, Registration]:
        """The district's registrations, read once per connector instance (one collection job)."""
        if district in self._listing:
            return self._listing[district]
        url = LISTINGS[district]
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
        if resolution.family != "official_records" or not resolution.may_collect:
            log_fetch(self.db, {**entry, "outcome": "not_allowed"})
            raise FetchError("not_allowed", f"{url} is not allowed by the official_records policy")
        decision = self.robots.decide(url)
        entry["robots"] = decision.basis if decision.allowed else f"disallowed ({decision.basis})"
        if not decision.allowed and policies.obeys_robots(resolution.policy):
            log_fetch(self.db, {**entry, "outcome": "robots_disallowed"})
            raise FetchError("robots_disallowed", f"robots.txt: {decision.basis}")
        try:
            response = self.client.get(url)
        except FetchError as exc:
            log_fetch(self.db, {**entry, "outcome": f"error:{exc.code}", "status_code": exc.status})
            raise
        entry["status_code"] = response.status
        if response.status >= 400:
            log_fetch(self.db, {**entry, "outcome": "refused" if response.status in (401, 403, 406, 451) else "error"})
            raise FetchError("refused", f"HTTP {response.status}; not worked around", status=response.status)
        registrations = parse_listing(response.text())
        if not registrations:
            log_fetch(self.db, {**entry, "outcome": "error:layout_changed"})
            raise FetchError("layout_changed", "no registrations found: the list's layout may have changed")
        log_fetch(self.db, {**entry, "outcome": "fetched"})
        self._listing[district] = registrations
        return registrations

    def item_for(self, registration: Registration) -> Item:
        dated = registration.dated
        return Item(
            connector_id=self.id,
            native_id=f"harera:{registration.rera_id}",
            canonical_url=PREVIEW.format(registration.preview_id) if registration.preview_id else LISTINGS["gurugram"],
            source_kind="registration_record",
            capture_level="full_content",
            title=f"HRERA registration {registration.rera_id}: {registration.name}",
            text=registration.text(),
            publication_date={
                "status": "known" if dated else "unknown",
                "value": datetime(dated.year, dated.month, dated.day, tzinfo=UTC) if dated else None,
                "precision": "day" if dated else None,
                "basis": "registry_record" if dated else None,
            },
            language="en",
        )

    def fetch_item(self, ref: str) -> Item:
        rera_id = ref.removeprefix("harera:")
        registration = self.listing().get(rera_id)
        if registration is None:
            raise FetchError("not_listed", f"{rera_id} is not on the HRERA list of registered projects")
        return self.item_for(registration)

    def check_availability(self, source: dict[str, Any]) -> Availability:
        from app.identity.text import nfc, sha256_text

        try:
            item = self.fetch_item(source["native_id"])
        except FetchError as exc:
            # A registration missing from the list may be revoked or lapsed; a person decides (never auto-deleted).
            return Availability("unknown", f"{exc.code}: {exc.message}")
        same = source.get("content_sha256") == sha256_text(nfc(item.text or ""))
        return Availability("present" if same else "changed", "unchanged" if same else "registry facts changed", item)

    def health(self) -> dict[str, Any]:
        return {"quota": {"limit": None, "used": None, "resets_at": None}}
