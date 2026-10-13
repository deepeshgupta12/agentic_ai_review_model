"""UC-53: the HRERA registry reader (Step 08.4, D53). A fictional list page with the real table's headers and the
fictional catalogue's TST registrations; no real registry data."""

from __future__ import annotations

from app.connectors.harera import parse_listing

from .test_collection import RESEARCHER, run_all_jobs, world  # noqa: F401  (world is a fixture)

HEADERS = [
    "Serial No.",
    "Registration Certificate Number",
    "Project ID",
    "Project Name",
    "Builder",
    "Project Location",
    "Project District",
    "Registered With",
    "Details of Project(Form A-H)",
    "Registration Up-to",
    "View Certificate",
    "View Quarterly Progress",
    "Monitoring Orders",
    "View OC/CC/PCC",
    "View Proceedings",
]


def row(serial, cert, code, name, valid, oc=False, preview="501"):
    cells = [
        str(serial),
        cert,
        code,
        name,
        "QUILLON DEVELOPERS LIMITED",
        "SECTOR 102, GURUGRAM",
        "GURUGRAM",
        "HRERA",
        f'<a href="https://haryanarera.gov.in/view_project/project_preview_open/{preview}">View</a>',
        valid,
        "<a>View</a>",
        "--",
        "--",
        '<a href="/oc/1.pdf">View</a>' if oc else "--",
        "--",
    ]
    return "<tr>" + "".join(f"<td>{c}</td>" for c in cells) + "</tr>"


def listing(*rows, headers=HEADERS):
    other = "<table><tr><th>Project Name</th><th>Document Type</th></tr><tr><td>x</td><td>y</td></tr></table>"
    head = "<tr>" + "".join(f"<th>{h}</th>" for h in headers) + "</tr>"
    return f"<html><body>{other}<table>{head}{''.join(rows)}</table></body></html>"


PAGE = listing(
    row(
        1,
        "TST/901/801/2023/11 DATED 18.12.2023",
        "RERA-TST-1406-2023",
        "QUILLON RESIDENCES PHASE 1",
        "30/06/2031",
        oc=True,
    ),
    row(
        2,
        "TST/902/802/2024/12 DATED 03.06.2024 (SUPERSEDES TST/662/394/2023/06 DATED 12.01.2023)",
        "RERA-TST-1521-2023",
        "QUILLON RESIDENCES PHASE 2",
        "31/12/2026",
        preview="502",
    ),
    row(3, "TST/999/999/2022/99 DATED 01.01.2022", "RERA-TST-0001-2022", "SOME OTHER PROJECT", "01/01/2027"),
)


def test_the_list_is_read_by_its_headers_into_dated_registry_facts():
    regs = parse_listing(PAGE)
    assert set(regs) == {"TST/901/801/2023/11", "TST/902/802/2024/12", "TST/999/999/2022/99"}
    one, two = regs["TST/901/801/2023/11"], regs["TST/902/802/2024/12"]
    assert str(one.dated) == "2023-12-18" and str(one.valid_upto) == "2031-06-30" and one.completion_certificate_listed
    assert (
        one.name == "QUILLON RESIDENCES PHASE 1"
        and one.preview_id == "501"
        and one.project_code == "RERA-TST-1406-2023"
    )
    assert two.supersedes == "TST/662/394/2023/06" and not two.completion_certificate_listed
    text = one.text()
    assert "Registration valid up to: 30 June 2031." in text and "certificate on the registry list: listed." in text
    assert "possession" not in text.lower(), "a registration's validity is never called a possession date"
    assert parse_listing(listing(row(1, "TST/901/801/2023/11", "X", "Y", "01/01/2030"), headers=HEADERS[:3])) == {}


def harera_page(world, page, status=200):  # noqa: F811
    world["net"].html("haryanarera.gov.in", {"/admincontrol/registered_projects/2": (status, page)})


def enable_registry(db, project_id):
    db["ai_project_configs"].update_one(
        {"_id": project_id, "sources.connector_id": "harera_registry"}, {"$set": {"sources.$.enabled": True}}
    )


def run_registry(db, settings, project_id):
    from app.sources.collection import start_run

    accepted = start_run(
        db.client, db, settings, project_id, {"window_days": 90, "connectors": ["harera_registry"]}, RESEARCHER
    )
    run_all_jobs(db)
    run = db["ai_runs"].find_one({"_id": accepted["run_id"]})
    return {c["connector_id"]: c for c in run["coverage"]}["harera_registry"]


def test_a_run_stores_each_registration_as_a_dated_official_record_matched_to_its_phase(db, settings, world):  # noqa: F811
    harera_page(world, PAGE)
    enable_registry(db, world["q"])
    cov = run_registry(db, settings, world["q"])
    assert cov["status"] == "complete_for_query" and cov["fetched"] == 2 and cov["matched"] == 2
    records = list(db["ai_sources"].find({"connector_id": "harera_registry"}).sort("native_id", 1))
    assert [r["native_id"] for r in records] == ["harera:TST/901/801/2023/11", "harera:TST/902/802/2024/12"]
    first = records[0]
    assert first["source_kind"] == "registration_record" and first["policy"]["family"] == "official_records"
    assert first["publication_date"]["basis"] == "registry_record" and first["publication_date"]["precision"] == "day"
    assert first["canonical_url"].endswith("/project_preview_open/501")
    link = db["ai_project_source_links"].find_one({"source.id": first["id"]})
    assert link["status"] == "auto_accepted" and link["phase"]["rera_id"] == "TST/901/801/2023/11"
    assert db["ai_evidence"].count_documents({"source.id": first["id"]}) == 1
    log = db["ai_fetch_log"].find_one({"connector_id": "harera_registry"})
    assert log["outcome"] == "fetched" and log["family"] == "official_records"


def test_the_same_facts_are_no_new_revision_and_a_changed_validity_is(db, settings, world):  # noqa: F811
    harera_page(world, PAGE)
    enable_registry(db, world["q"])
    run_registry(db, settings, world["q"])
    again = run_registry(db, settings, world["q"])
    assert "unchanged: 2" in again["note"]
    harera_page(world, PAGE.replace("30/06/2031", "30/06/2032"))
    changed = run_registry(db, settings, world["q"])
    assert "changed: 1" in changed["note"]
    revisions = sorted(r["revision"] for r in db["ai_sources"].find({"native_id": "harera:TST/901/801/2023/11"}))
    assert revisions == [1, 2]


def test_a_registration_missing_from_the_list_or_a_changed_layout_is_reported_not_guessed(db, settings, world):  # noqa: F811
    harera_page(
        world, listing(row(1, "TST/901/801/2023/11 DATED 18.12.2023", "X", "QUILLON RESIDENCES PHASE 1", "30/06/2031"))
    )
    enable_registry(db, world["q"])
    cov = run_registry(db, settings, world["q"])
    assert "not listed: TST/902/802/2024/12" in cov["note"] and cov["fetched"] == 1
    harera_page(world, "<html><body><table><tr><th>Something else</th></tr></table></body></html>")
    cov = run_registry(db, settings, world["q"])
    assert cov["status"] == "unavailable" and "layout_changed" in cov["note"]
    harera_page(world, "denied", status=403)
    cov = run_registry(db, settings, world["q"])
    assert cov["status"] == "unavailable" and "refused" in cov["note"]


def test_each_project_is_looked_up_in_its_own_states_registry_or_reported_as_not_covered():
    from app.connectors.registries import reader_for, state_of

    assert state_of({"city": "Gurugram"}) == "haryana" and state_of({"city": "Gurgaon"}) == "haryana"
    assert state_of({"city": "Pune"}) == "maharashtra" and state_of({"city": "Noida"}) == "uttar pradesh"
    assert state_of({"city": "Somewhere", "state": "Kerala"}) == "kerala", "the input's state wins"
    assert reader_for({"city": "Gurgaon"}) == ("harera_registry", None)
    assert reader_for({"city": "Bengaluru"}) == ("state_registry", None), "Karnataka has a portal reader"
    connector, reason = reader_for({"city": "Shimla", "state": "Himachal Pradesh"})
    assert connector is None and "no registry reader for Himachal Pradesh yet" in reason
    connector, reason = reader_for({"city": "Unknownpur"})
    assert connector is None and "add the project's state" in reason
