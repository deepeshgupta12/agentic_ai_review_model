"""UC-40: run, source and connector-health APIs (Step 05; journeys J02, J03, J12, J16). Fictional data only."""

from __future__ import annotations

from app.identity.intake import store_text_source
from app.identity.service import identify_source
from app.workers.worker import run_one

from .conftest import sign_in
from .test_collection import world  # noqa: F401  (fixture)


def start(api, headers, project_id, key="run-key-0001", body=None):
    return api.post(
        f"/v1/projects/{project_id}/runs",
        json=body or {"window_days": 30, "connectors": None},
        headers={**headers, "Idempotency-Key": key},
    )


def test_start_run_needs_a_key_a_researcher_and_replays(api, db, make_user, contracts, fictional):
    q = fictional["Quillon Residences"]
    analyst = sign_in(api, make_user, ["analyst"])
    assert start(api, analyst, q).status_code == 403
    researcher = sign_in(api, make_user, ["researcher"])
    no_key = api.post(f"/v1/projects/{q}/runs", json={"window_days": 30, "connectors": None}, headers=researcher)
    assert no_key.status_code == 422
    first = start(api, researcher, q)
    assert first.status_code == 202 and contracts.errors(first.json(), "api.schema.json#/$defs/Accepted") == []
    assert start(api, researcher, q).json() == first.json(), "same key and body: the same run"
    assert db["ai_runs"].count_documents({}) == 1
    bad = start(api, researcher, q, key="run-key-0002", body={"window_days": 30, "connectors": ["reddit_api"]})
    assert bad.status_code == 422


def test_run_list_read_and_cancel(api, db, make_user, contracts, world):  # noqa: F811
    q = world["q"]
    researcher = sign_in(api, make_user, ["researcher"])
    run_id = start(api, researcher, q).json()["run_id"]
    page = api.get(f"/v1/projects/{q}/runs", headers=researcher)
    assert page.status_code == 200 and contracts.errors(page.json(), "api.schema.json#/$defs/RunPage") == []
    got = api.get(f"/v1/runs/{run_id}", headers=researcher)
    assert got.status_code == 200 and got.json()["stage"] == "collecting"
    assert api.post(f"/v1/runs/{run_id}/cancel", json={"reason": ""}, headers=researcher).status_code == 422
    moderator = sign_in(api, make_user, ["moderator"])
    assert api.post(f"/v1/runs/{run_id}/cancel", json={"reason": "x"}, headers=moderator).status_code == 403
    researcher = sign_in(api, make_user, ["researcher"])
    cancelled = api.post(f"/v1/runs/{run_id}/cancel", json={"reason": "Wrong window"}, headers=researcher)
    assert (
        cancelled.status_code == 202
        and api.get(f"/v1/runs/{run_id}", headers=researcher).json()["stage"] == "cancelled"
    )
    assert api.get("/v1/runs/run_01K0000000000000000000000Z", headers=researcher).status_code == 404


def parse_sse(text):
    events = []
    for block in text.strip().split("\n\n"):
        fields = dict(line.split(": ", 1) for line in block.splitlines() if ": " in line)
        if "id" in fields:
            events.append(fields)
    return events


def test_run_events_stream_and_resume(api, db, make_user, contracts, fictional):
    q = fictional["Quillon Residences"]
    researcher = sign_in(api, make_user, ["researcher"])
    run_id = start(api, researcher, q).json()["run_id"]  # no credentials: the run finishes at once
    response = api.get(f"/v1/runs/{run_id}/events", headers=researcher)
    assert response.status_code == 200 and response.headers["content-type"].startswith("text/event-stream")
    events = parse_sse(response.text)
    assert [e["event"] for e in events] == ["stage_changed", "stage_changed", "completed"]
    import json

    for e in events:
        assert contracts.errors(json.loads(e["data"]), "api.schema.json#/$defs/RunEvent") == []
    resumed = api.get(f"/v1/runs/{run_id}/events", headers={**researcher, "Last-Event-ID": events[0]["id"]})
    assert [e["id"] for e in parse_sse(resumed.text)] == [e["id"] for e in events[1:]]


def test_sources_list_detail_and_utf16_offsets(api, db, make_user, contracts, fictional):
    q = fictional["Quillon Residences"]
    text = "Quillon Residences in Sector 102 😀👍 parking is tight"
    source = store_text_source(
        db,
        connector_id="web_fetch",
        native_id="https://nobroker.in/e",
        canonical_url="https://nobroker.in/e",
        source_kind="forum_post",
        text=text,
        policy_family="competitor_portals",
        publication_date={
            "status": "approximate",
            "value": "2026-08-14T00:00:00Z",
            "precision": "day",
            "basis": "page_markup",
        },
    )
    identify_source(db.client, db, contracts, source, focus_project_ids=[q])
    analyst = sign_in(api, make_user, ["analyst"])
    page = api.get(f"/v1/projects/{q}/sources", headers=analyst)
    assert page.status_code == 200 and contracts.errors(page.json(), "api.schema.json#/$defs/SourcePage") == []
    [item] = page.json()["items"]
    assert item["link_status"] == "auto_accepted" and item["aspects"] == []
    assert api.get(f"/v1/projects/{q}/sources?published_from=2026-09-01", headers=analyst).json()["items"] == []
    assert len(api.get(f"/v1/projects/{q}/sources?published_to=2026-08-31", headers=analyst).json()["items"]) == 1
    assert api.get(f"/v1/projects/{q}/sources?aspect=possession", headers=analyst).json()["items"] == []
    detail = api.get(f"/v1/sources/{source['id']}/revisions/1", headers=analyst)
    assert detail.status_code == 200
    assert contracts.errors(detail.json(), "api.schema.json#/$defs/SourceRevisionDetail") == []
    [view] = detail.json()["evidence"]
    assert view["eligible"] and view["anchor_view"]["utf16_end"] == len(text) + 2, "two emoji count twice in UTF-16"
    assert detail.json()["permitted_text"] == text


def test_withdrawal_through_the_api(api, db, make_user, contracts, fictional):
    q = fictional["Quillon Residences"]
    source = store_text_source(
        db,
        connector_id="web_fetch",
        native_id="https://nobroker.in/w",
        canonical_url="https://nobroker.in/w",
        source_kind="forum_post",
        text="Quillon Residences, Sector 102: lifts are slow.",
        policy_family="competitor_portals",
    )
    identify_source(db.client, db, contracts, source, focus_project_ids=[q])
    body = {"scope": "source_revision", "revision": 1, "reason": "Author asked"}
    analyst = sign_in(api, make_user, ["analyst"])
    url = f"/v1/sources/{source['id']}/withdrawals"
    assert api.post(url, json=body, headers={**analyst, "Idempotency-Key": "withdraw-0001"}).status_code == 403
    moderator = sign_in(api, make_user, ["moderator"])
    assert api.post(url, json=body, headers=moderator).status_code == 422, "Idempotency-Key required"
    accepted = api.post(url, json=body, headers={**moderator, "Idempotency-Key": "withdraw-0001"})
    assert accepted.status_code == 202 and contracts.errors(accepted.json(), "api.schema.json#/$defs/Accepted") == []
    while run_one(db, "test-worker", 60) is not None:
        pass
    detail = api.get(f"/v1/sources/{source['id']}/revisions/1", headers=moderator).json()
    assert detail["permitted_text"] is None and detail["source"]["lifecycle"] == "withdrawn"
    assert "source_withdrawn" in detail["evidence"][0]["ineligibility_reasons"]


def test_connector_health_reports_real_activity(api, db, make_user, contracts, settings, world):  # noqa: F811
    from app.sources.collection import start_run

    start_run(
        db.client,
        db,
        settings,
        world["q"],
        {"window_days": 30, "connectors": None},
        {"kind": "user", "user_id": "usr_01K00000000000000000000001", "role": "researcher"},
    )
    while run_one(db, "test-worker", 60) is not None:
        pass
    researcher = sign_in(api, make_user, ["researcher"])
    health = api.get("/v1/connectors/health", headers=researcher)
    assert (
        health.status_code == 200
        and contracts.errors(health.json(), "api.schema.json#/$defs/ConnectorHealthList") == []
    )
    rows = {r["connector_id"]: r for r in health.json()["connectors"]}
    assert rows["brave_search"]["quota"]["used"] > 0 and rows["brave_search"]["last_success_at"] is not None
    assert rows["web_fetch"]["last_success_at"] is not None, "the web reader's record is the fetch log"
    assert rows["youtube_data_api"]["quota"]["limit"] == settings.youtube_daily_searches


def test_a_source_whose_link_the_rules_rejected_still_matches_the_contract(api, db, make_user, contracts, fictional):
    """Found by the Step 05 check on real data: rule-rejected links carry no decision (D45)."""
    source = store_text_source(
        db,
        connector_id="web_fetch",
        native_id="https://nobroker.in/p",
        canonical_url="https://nobroker.in/p",
        source_kind="forum_post",
        text="Quillon Residences in Pune has a lovely clubhouse.",
        policy_family="competitor_portals",
    )
    report = identify_source(db.client, db, contracts, source, focus_project_ids=[fictional["Quillon Residences"]])
    assert [r["status"] for r in report["links"]] == ["rejected"]
    analyst = sign_in(api, make_user, ["analyst"])
    detail = api.get(f"/v1/sources/{source['id']}/revisions/1", headers=analyst)
    assert detail.status_code == 200 and detail.json()["links"][0]["decided_by"] is None
    assert contracts.errors(detail.json(), "api.schema.json#/$defs/SourceRevisionDetail") == []
