"""UC-39 (continued): availability re-checks of stored sources (Step 05.6; D44). A fake internet only."""

from __future__ import annotations

from datetime import UTC, datetime

from app.sources.recheck import start_recheck

from .fakenet import article
from .test_collection import PAGE_TEXT, run_all_jobs, start, world  # noqa: F401  (world is a fixture)

PAGE = "https://forum.example.test/t/1"


def collected(db, settings, world):  # noqa: F811
    start(db, settings, world["q"])
    run_all_jobs(db)
    return db["ai_sources"].find_one({"connector_id": "web_fetch"})


def recheck(db, project_id=None):
    job_id = start_recheck(db, project_id)["job_id"]
    db["ai_jobs"].update_one({"_id": job_id}, {"$set": {"logical_key": f"done:{job_id}"}})  # the next one is new
    run_all_jobs(db)
    return db["ai_audit_events"].find_one({"action": "sources.rechecked", "target.id": job_id})["details"]


def forum(world, status, body=None):  # noqa: F811
    world["net"].html(
        "forum.example.test", {"/t/1": (status, body or article("Quillon Residences review", PAGE_TEXT * 4))}
    )


def lifecycle(db, source):
    return db["ai_sources"].find_one({"_id": source["_id"]})["lifecycle"]


def test_a_page_gone_twice_is_deleted_and_erased_but_once_is_only_unavailable(db, settings, world):  # noqa: F811
    page = collected(db, settings, world)
    forum(world, 410)
    assert recheck(db)["gone"] >= 1 and lifecycle(db, page) == "unavailable"
    result = recheck(db)
    assert result["deleted"] >= 1 and lifecycle(db, page) == "deleted"
    assert db["ai_sources"].find_one({"_id": page["_id"]})["payload_ref"] is None, "text erased after invalidation"


def test_a_temporary_failure_recovers_without_losing_anything(db, settings, world):  # noqa: F811
    page = collected(db, settings, world)
    forum(world, 503)
    assert recheck(db)["unknown"] >= 1 and lifecycle(db, page) == "unavailable"
    forum(world, 200)
    assert recheck(db)["present"] >= 1 and lifecycle(db, page) == "active"
    assert db["ai_jobs"].count_documents({"kind": "erase_payloads"}) == 0


def test_an_edited_page_becomes_a_new_revision_linked_to_the_same_project(db, settings, world):  # noqa: F811
    page = collected(db, settings, world)
    old_link = db["ai_project_source_links"].find_one({"source.id": page["id"], "source.revision": 1})
    edited = "Quillon Residences in Sector 102: the road has now been repaired and the lifts work. " * 5
    forum(world, 200, article("Quillon Residences review", edited))
    assert recheck(db, world["q"])["new_revisions"] == 1
    assert lifecycle(db, page) == "superseded"
    new = db["ai_sources"].find_one({"id": page["id"], "revision": 2})
    assert new["lifecycle"] == "active"
    link = db["ai_project_source_links"].find_one({"source.id": page["id"], "source.revision": 2})
    assert link["project_id"] == world["q"] and link["status"] == "auto_accepted"
    assert db["ai_jobs"].find_one({"kind": "invalidate_dependencies", "logical_key": {"$regex": old_link["_id"]}})


def test_a_stated_date_the_markup_does_not_support_is_corrected_with_an_audit_event(db, settings, world):  # noqa: F811
    page = collected(db, settings, world)
    guessed = {
        "status": "approximate",
        "value": datetime(2026, 9, 29, tzinfo=UTC),
        "precision": "day",
        "basis": "page_markup",
    }
    db["ai_sources"].update_one({"_id": page["_id"]}, {"$set": {"publication_date": guessed}})
    assert recheck(db)["dates_corrected"] == 1
    date = db["ai_sources"].find_one({"_id": page["_id"]})["publication_date"]
    assert date["value"] == datetime(2026, 8, 14, tzinfo=UTC), "the page's meta tag"
    event = db["ai_audit_events"].find_one({"action": "source.date_corrected"})
    assert "2026-09-29" in event["details"]["from"] and "2026-08-14" in event["details"]["to"]
    assert recheck(db).get("dates_corrected", 0) == 0, "nothing to correct the second time"


def test_a_removed_video_is_deleted_after_two_checks_and_without_a_key_nothing_is_checked(db, settings, world):  # noqa: F811
    collected(db, settings, world)
    video = db["ai_sources"].find_one({"source_kind": "video"})
    world["net"].json(  # the video is removed; its comments still answer
        "www.googleapis.com",
        lambda r: (200, {"items": []} if r.url.path.endswith("/videos") else {"items": [{"id": "c"}]}),
    )
    recheck(db)
    recheck(db)
    assert lifecycle(db, video) == "deleted"
    assert db["ai_sources"].count_documents({"source_kind": "comment", "lifecycle": "active"}) > 0
    settings.youtube_api_key = None
    comments = db["ai_sources"].count_documents(
        {"connector_id": "youtube_data_api", "source_kind": "comment", "lifecycle": "active"}
    )
    result = recheck(db)
    assert result["not_checked_no_access"] == comments, "Reddit is never re-checked (no deletion check; retention)"
