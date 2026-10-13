"""UC-67: registration records from the other states' RERA portals (D57), against fakes: found by number (portal
address or Brave on the portal's domain), kept only if they state the number, reduced to registry facts with
personal details removed, and stored as dated primary records; a number not found is named in the coverage."""

from __future__ import annotations

import json

import httpx
from pydantic import SecretStr

from app.connectors import registry
from app.connectors.registries import reader_for
from app.connectors.scrapfly import Scrapfly
from app.connectors.state_registry import StateRegistry, pdf_text, registry_facts
from app.sources import collection
from app.sources.robots import RobotsCache

from .fakenet import FakeNet
from .test_collection import run_all_jobs, start

NUMBER = "UPRERAPRJ123456/01/2025"
OTHER = "UPRERAPRJ999999/09/2025"


def tiny_pdf(lines: list[str]) -> bytes:
    """A one-page PDF with a real text layer (what a portal's registration certificate looks like to pypdf)."""
    content = "BT /F1 10 Tf 50 750 Td " + " ".join(f"({line}) Tj 0 -14 Td" for line in lines) + " ET"
    objects = [
        "<< /Type /Catalog /Pages 2 0 R >>",
        "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R "
        "/Resources << /Font << /F1 5 0 R >> >> >>",
        f"<< /Length {len(content)} >>\nstream\n{content}\nendstream",
        "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = b"%PDF-1.4\n"
    offsets = []
    for index, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{index} 0 obj\n{body}\nendobj\n".encode()
    xref = len(out)
    out += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode()
    out += b"".join(f"{o:010d} 00000 n \n".encode() for o in offsets)
    out += f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF".encode()
    return out


CERTIFICATE = tiny_pdf(
    [
        "REGISTRATION CERTIFICATE OF PROJECT",
        f"Project Registration Number- {NUMBER}",
        "Project Name : Quillon Residences",
        "District/State : Noida/Uttar Pradesh",
        "Proposed Completion Date : 30-06-2029",
        "Promoter Name : Brightwell Estates Pvt Ltd, phone 9876543210",
        "1. This registration is granted subject to the following conditions",
        "i. The promoter shall enter into an agreement for sale",
    ]
)


def network(portal_status=200):
    net = FakeNet()

    def brave(request: httpx.Request) -> httpx.Response:
        q = request.url.params["q"]
        results = []
        if NUMBER in q:
            results = [
                {"url": "https://www.up-rera.in/ViewDocument?Param=other.pdf", "title": "another certificate"},
                {"url": "https://www.up-rera.in/ViewDocument?Param=111.pdf", "title": "Registration certificate"},
                {"url": "https://www.example-aggregator.test/quillon", "title": "not the portal"},
            ]
        body = {"query": {"more_results_available": False}, "web": {"results": results}}
        return httpx.Response(200, headers={"content-type": "application/json"}, content=json.dumps(body).encode())

    def portal(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return httpx.Response(200, headers={"content-type": "text/plain"}, text="User-agent: *\nDisallow: /\n")
        if portal_status != 200:
            return httpx.Response(portal_status, headers={"content-type": "text/html"}, text="Forbidden")
        param = request.url.params.get("Param", "")
        pdf = CERTIFICATE if param == "111.pdf" else tiny_pdf([f"Project Registration Number- {OTHER}"])
        return httpx.Response(200, headers={"content-type": "application/pdf"}, content=pdf)

    def scrapfly(request: httpx.Request) -> httpx.Response:
        page = (
            f"<html><body><table><tr><td>Registration Number</td></tr><tr><td>{NUMBER}</td></tr></table>"
            "<p>Project Name: Quillon Residences</p><p>Director mobile 9876543210, email a@b.in</p>"
            "<p>Project Status: Ongoing</p></body></html>"
        )
        body = {"result": {"status_code": 200, "content": page}}
        return httpx.Response(200, headers={"content-type": "application/json"}, content=json.dumps(body).encode())

    net.json("api.search.brave.com", lambda r: (200, json.loads(brave(r).content)))
    net.route("www.up-rera.in", portal)
    net.route("api.scrapfly.io", scrapfly)
    return net


def reader(db, settings, net, with_scrapfly=False):
    settings.brave_search_api_key = SecretStr("test-only-brave-key-0000")
    client = net.client()
    brave = registry.build("brave_search", db, settings)
    brave.client = client
    scrapfly = Scrapfly("test-only-scrapfly-key-0000", client, db, settings) if with_scrapfly else None
    return StateRegistry(client, RobotsCache(client, "ProjectIntelligenceBot"), db, brave, scrapfly)


def test_each_state_goes_to_its_reader():
    assert reader_for({"city": "Noida"}) == ("state_registry", None)
    assert reader_for({"city": "Bengaluru"}) == ("state_registry", None)
    assert reader_for({"city": "Gurgaon"}) == ("harera_registry", None)
    connector, reason = reader_for({"city": "Shimla", "state": "Himachal Pradesh"})
    assert connector is None and "Himachal Pradesh" in reason


def test_registry_facts_keep_the_record_and_drop_personal_details():
    text = pdf_text(CERTIFICATE)
    assert NUMBER in text and "Proposed Completion Date" in text, "the certificate's text layer is read"
    facts = registry_facts(text, is_pdf=True)
    assert "Proposed Completion Date : 30-06-2029" in facts and "agreement for sale" not in facts, (
        "up to the conditions"
    )
    assert "9876543210" not in facts and "[removed]" in facts
    html = "Registration Number: X1\nRandom heading\nProject Status: Ongoing\nDirector: Mr A, mobile 9876543210"
    assert registry_facts(html, is_pdf=False) == "Registration Number: X1\nProject Status: Ongoing"


def test_the_record_is_the_page_that_states_the_number(db, settings):
    item = reader(db, settings, network()).record("uttar pradesh", NUMBER)
    assert item is not None and item.source_kind == "registration_record"
    assert item.canonical_url == "https://www.up-rera.in/ViewDocument?Param=111.pdf", "another certificate is skipped"
    assert item.text.startswith(f"UP RERA registration {NUMBER} (Uttar Pradesh).")
    assert "Proposed Completion Date : 30-06-2029" in item.text and "9876543210" not in item.text
    outcomes = [log["outcome"] for log in db["ai_fetch_log"].find({"connector_id": "state_registry"}).sort("at", 1)]
    assert outcomes[:3] == ["fetched", "number_not_on_page", "fetched"]
    assert all(log["robots"].startswith("disallowed") for log in db["ai_fetch_log"].find({"outcome": "fetched"})), (
        "robots.txt recorded, not enforced (D61)"
    )


def test_a_refused_portal_is_read_through_scrapfly_and_unknown_numbers_find_nothing(db, settings):
    item = reader(db, settings, network(portal_status=403), with_scrapfly=True).record("uttar pradesh", NUMBER)
    assert item is not None and "Project Status: Ongoing" in item.text and "9876543210" not in item.text
    assert "a@b.in" not in item.text
    assert reader(db, settings, network()).record("uttar pradesh", "UPRERAPRJ000000/00/2000") is None


def test_a_run_for_a_project_in_another_state_stores_its_registry_record(
    db, settings, contracts, fictional, monkeypatch
):
    net = network()
    settings.brave_search_api_key = SecretStr("test-only-brave-key-0000")
    settings.crawler_min_seconds_per_host = 0
    monkeypatch.setattr(registry, "safe_client", lambda _s: net.client())
    monkeypatch.setattr(collection, "get_settings", lambda: settings)
    q = fictional["Quillon Residences"]
    registration = {"id": NUMBER, "id_normalised": NUMBER, "registered_name": "Quillon Residences"}
    db["projects"].update_one({"_id": q}, {"$set": {"city": "Noida", "rera_registrations": [registration]}})
    db["ai_project_configs"].update_one(
        {"_id": q, "sources.connector_id": "harera_registry"}, {"$set": {"sources.$.enabled": True}}
    )
    accepted = start(db, settings, q, connectors=["brave_search", "harera_registry"])
    run_all_jobs(db)
    cov = {c["connector_id"]: c for c in db["ai_runs"].find_one({"_id": accepted["run_id"]})["coverage"]}
    assert cov["harera_registry"]["note"].startswith("UP RERA: 1 of 1 registration records found")
    record = db["ai_sources"].find_one({"connector_id": "state_registry"})
    assert record["source_kind"] == "registration_record" and record["policy"]["family"] == "official_records"


def test_orders_and_cause_lists_that_mention_the_number_are_never_kept():
    """Found live on 13 Oct 2026: a MahaRERA search for a project number returned a tribunal cause list naming
    appellants and advocates. Only a registration record is kept."""
    cause_list = f"Combined cause list\nAppeal No. 711/23\nMahaRERA Reg No. {NUMBER}\nAppellants Respondents Adv."
    assert StateRegistry.not_a_record(cause_list, NUMBER, is_pdf=True) == "proceedings_not_a_record"
    assert StateRegistry.not_a_record(f"Brochure for {NUMBER}", NUMBER, is_pdf=True) == "not_a_certificate"
    assert StateRegistry.not_a_record(f"{NUMBER} news", NUMBER, is_pdf=False) == "no_registry_facts"
    assert StateRegistry.not_a_record(pdf_text(CERTIFICATE), NUMBER, is_pdf=True) is None
