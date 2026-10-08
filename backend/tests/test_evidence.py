"""UC-47..UC-51: the evidence layer (Step 07). Fictional catalogue only."""

from __future__ import annotations

from app.contracts import to_view
from app.evidence.clusters import cluster_origins, independent_origins
from app.evidence.similarity import normalise, words
from app.identity.intake import store_text_source
from app.identity.service import identify_source
from app.media.fetch import CaptionTrack

from .test_collection import world  # noqa: F401  (a fixture)
from .test_media import video  # noqa: F401  (a fixture)

POST = (
    "Visited Quillon Residences in Sector 102 last weekend. The sample flat was bright and airy, "
    "but the approach road is still broken and the builder could not give a possession date."
)


def source(db, contracts, fictional, native_id, text, kind="forum_post", family="competitor_portals"):
    doc = store_text_source(
        db,
        connector_id="web_fetch",
        native_id=f"https://nobroker.in/{native_id}",
        canonical_url=f"https://nobroker.in/{native_id}",
        source_kind=kind,
        text=text,
        policy_family=family,
    )
    identify_source(db.client, db, contracts, doc, focus_project_ids=[fictional["Quillon Residences"]])
    return doc


def evidence_of(db, doc):
    return list(db["ai_evidence"].find({"source.id": doc["id"]}))


def cluster_of(db, doc):
    return evidence_of(db, doc)[0]["origin_cluster"]


# --- UC-47: normalisation and origin clusters --------------------------------------------------------------------


def test_normalising_keeps_hindi_words_and_numbers_whole():
    assert normalise("कीमत एक करोड़ है। Price ₹1.75 crore, 18,500/sq ft! https://x.in/a") == (
        "कीमत एक करोड़ है price 1.75 crore 18500 sq ft"
    )
    assert words("यह प्रोजेक्ट बहुत अच्छा है") == ["यह", "प्रोजेक्ट", "बहुत", "अच्छा", "है"]


def test_three_copies_of_one_post_count_as_one_origin(db, contracts, fictional):
    a = source(db, contracts, fictional, "a", POST)
    b = source(db, contracts, fictional, "b", POST.upper() + "  ")
    c = source(db, contracts, fictional, "c", POST.replace(".", "!") + " https://t.co/xyz")
    report = cluster_origins(db.client, db)
    assert report["joined"] == 1 and report["clusters"] == 1
    assert cluster_of(db, a) == cluster_of(db, b) == cluster_of(db, c)
    refs = [{"id": e["id"], "revision": e["revision"]} for d in (a, b, c) for e in evidence_of(db, d)]
    assert len(refs) == 3 and len(independent_origins(db, refs)) == 1, "three copies, one opinion"
    cluster = db["ai_origin_clusters"].find_one({"_id": cluster_of(db, a)["id"]})
    assert cluster["method"] == "exact_hash" and len(cluster["members"]) == 3
    assert contracts.errors(to_view(cluster), "sources.schema.json#/$defs/OriginCluster") == []


def test_a_lightly_edited_copy_and_a_copied_paragraph_join_the_origin(db, contracts, fictional):
    article = (
        "Quillon Residences in Sector 102 is the project everyone in the area is talking about this year. "
        "The towers are rising quickly, two of them have reached their full height, and the clubhouse frame is up. "
        "Buyers we spoke to praised the layouts and the light in the corner units, but several said the approach "
        "road floods after rain and that the builder has not confirmed when possession will begin. "
        "Prices have moved up since the launch, and resale listings now ask noticeably more than the launch rate."
    )
    original = source(db, contracts, fictional, "orig", article)
    edited = source(
        db, contracts, fictional, "edit", article.replace("this year", "these days")
    )  # syndicated, retitled
    short_edit = source(db, contracts, fictional, "short", POST.replace("last weekend", "on Sunday"))
    longer = (
        "Broker note on Gurgaon projects for this month. " * 3
        + "\n\n"
        + article
        + "\n\nCall us for site visits across Sector 102 and nearby sectors any day of the week."
    )
    copier = source(db, contracts, fictional, "copy", longer)
    cluster_origins(db.client, db)
    assert cluster_of(db, original) == cluster_of(db, edited) == cluster_of(db, copier)
    assert cluster_of(db, short_edit) != cluster_of(db, original), "a short post with edits is not called a copy"
    cluster = db["ai_origin_clusters"].find_one({"_id": cluster_of(db, original)["id"]})
    assert cluster["method"] == "near_duplicate"
    assert cluster["representative"] == {"id": original["id"], "revision": 1}, "the earliest copy represents it"


def test_short_identical_comments_stay_separate_opinions(db, contracts, fictional):
    short = "Quillon Residences Sector 102 is nice"
    people = [source(db, contracts, fictional, f"s{i}", short, kind="comment") for i in range(3)]
    other = source(db, contracts, fictional, "other", POST.replace("broken", "fine").replace("could not", "did"))
    cluster_origins(db.client, db)
    clusters = {cluster_of(db, p)["id"] for p in people}
    assert len(clusters) == 3, "too short to call a copy"
    assert cluster_of(db, other)["id"] not in clusters


def test_cluster_ids_are_stable_and_membership_changes_are_versions(db, contracts, fictional):
    from app.sources.lifecycle import withdraw

    from .test_lifecycle import MODERATOR

    a = source(db, contracts, fictional, "a", POST)
    b = source(db, contracts, fictional, "b", POST)
    cluster_origins(db.client, db)
    first = cluster_of(db, a)
    assert cluster_origins(db.client, db)["changed"] == 0, "nothing new, nothing written"
    c = source(db, contracts, fictional, "c", POST)
    cluster_origins(db.client, db)
    assert cluster_of(db, c) == {"id": first["id"], "version": 2} == cluster_of(db, a)
    body = {"scope": "source_all_revisions", "revision": None, "reason": "Author asked"}
    withdraw(db.client, db, contracts, b["id"], body, MODERATOR)
    from app.workers.worker import run_one

    while run_one(db, "test-worker", 60) is not None:
        pass
    cluster_origins(db.client, db)
    assert cluster_of(db, a) == {"id": first["id"], "version": 3}, "the erased copy left the cluster"
    assert cluster_of(db, b)["id"] != first["id"]
    assert db["ai_audit_events"].count_documents({"action": "origin_clusters.updated"}) == 3


# --- shared helpers for UC-48..UC-51 -------------------------------------------------------------------------------


def source_for(db, contracts, project_id, native_id, text, kind="forum_post"):
    doc = store_text_source(
        db,
        connector_id="web_fetch",
        native_id=f"https://nobroker.in/{native_id}",
        canonical_url=f"https://nobroker.in/{native_id}",
        source_kind=kind,
        text=text,
        policy_family="competitor_portals",
    )
    identify_source(db.client, db, contracts, doc, focus_project_ids=[project_id])
    return doc


def ref(doc):
    return {"id": doc["id"], "revision": doc["revision"]}


def run_jobs(db):
    from app.workers.worker import run_one

    while run_one(db, "test-worker", 60) is not None:
        pass


ISO = __import__("re").compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?Z$")


def stored(value):
    """A contract fixture view as MongoDB stores it: timestamps as datetimes."""
    from datetime import datetime

    if isinstance(value, dict):
        return {k: stored(v) for k, v in value.items()}
    if isinstance(value, list):
        return [stored(v) for v in value]
    if isinstance(value, str) and ISO.match(value):
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    return value


def fixture(file, name):
    import json

    from .conftest import fixture_path

    cases = json.loads(fixture_path("contracts", "v1", "fixtures", file).read_text(encoding="utf-8"))["cases"]
    return next(c["instance"] for c in cases if c["name"] == name)


def lineage_for(db, evidence, *, lifecycle="approved"):
    """A claim, a finding and a content revision citing this evidence, built from the contract fixtures."""
    from app.ids import new_id

    claim = stored(fixture("evidence.json", "claim_opinion_many_origins"))
    claim.update(
        id=new_id("clm"),
        project_id=evidence["project_id"],
        supporting_evidence=[ref(evidence)],
        origin_clusters=[],
        independent_origin_count=1,
        created_by_task=new_id("tsk"),
    )
    claim["_id"] = f"{claim['id']}@1"
    finding = stored(fixture("evidence.json", "finding_con"))
    finding.update(
        id=new_id("fnd"),
        project_id=evidence["project_id"],
        claims=[ref(claim)],
        origin_clusters=[],
        independent_origin_count=1,
        created_by={"kind": "agent", "task_id": new_id("tsk"), "actor": None},
    )
    finding["_id"] = f"{finding['id']}@1"
    content = stored(fixture("content.json", "content_revision_approved"))
    content.pop("id")
    content["_id"] = new_id("rev")
    content["project_id"] = evidence["project_id"]
    content["payload"]["project"]["id"] = evidence["project_id"]
    content["revision"] = db["ai_content_revisions"].count_documents({}) + 1
    content["lifecycle"] = lifecycle
    content["manifest"] = {
        "findings": [ref(finding)],
        "claims": [ref(claim)],
        "reviews": [],
        "evidence": [ref(evidence)],
        "sources": [evidence["source"]],
        "links": [evidence["link_id"]],
        "policies": [evidence["policy"]],
        "eligibility_epoch": 1,
    }
    db["ai_claims"].insert_one(claim)
    db["ai_findings"].insert_one(finding)
    db["ai_content_revisions"].insert_one(content)
    return claim, finding, content


# --- UC-48: one eligibility rule ----------------------------------------------------------------------------------


def test_one_eligibility_rule_serves_support_identity_and_the_api(db, contracts, fictional):
    from app.evidence.eligibility import eligibility

    doc = source(db, contracts, fictional, "a", POST)
    e = evidence_of(db, doc)[0]
    assert eligibility(db, e).eligible and eligibility(db, e).flags == []
    db["ai_sources"].update_one({"_id": doc["_id"]}, {"$set": {"lifecycle": "stale"}})
    assert eligibility(db, e).eligible and eligibility(db, e).flags == ["stale"], "stale is flagged, not blocked"
    db["ai_sources"].update_one({"_id": doc["_id"]}, {"$set": {"lifecycle": "unavailable"}})
    assert eligibility(db, e).reasons == ["source_unavailable"], "not used while temporarily unavailable"
    db["ai_sources"].update_one({"_id": doc["_id"]}, {"$set": {"lifecycle": "active"}})
    db["ai_project_source_links"].update_one({"_id": e["link_id"]}, {"$set": {"status": "needs_review"}})
    assert eligibility(db, e).reasons == ["link_not_accepted"]
    assert eligibility(db, e, for_identity=True).eligible, "identity work may use a link still in review"
    db["ai_project_source_links"].update_one({"_id": e["link_id"]}, {"$set": {"status": "accepted"}})
    other = {**e, "project_id": fictional["Tavira Vista"]}
    assert "link_not_accepted" in eligibility(db, other).reasons, "a link of another project never supports this one"


def test_the_retrieval_filter_admits_exactly_what_the_rule_admits(db, contracts, fictional):
    from app.evidence.eligibility import eligibility, eligible_filter

    q = fictional["Quillon Residences"]
    docs = [
        source(db, contracts, fictional, f"p{i}", POST + f" Visit number {i} was in the evening.") for i in range(5)
    ]
    evidence = [evidence_of(db, d)[0] for d in docs]
    db["ai_sources"].update_one({"_id": docs[1]["_id"]}, {"$set": {"lifecycle": "stale"}})
    db["ai_sources"].update_one({"_id": docs[2]["_id"]}, {"$set": {"lifecycle": "unavailable"}})
    db["ai_project_source_links"].update_one({"_id": evidence[3]["link_id"]}, {"$set": {"status": "needs_review"}})
    db["ai_sources"].update_one({"_id": docs[4]["_id"]}, {"$set": {"lifecycle": "superseded"}})
    by_rule = {e["_id"] for e in db["ai_evidence"].find({"project_id": q}) if eligibility(db, e).eligible}
    by_filter = {e["_id"] for e in db["ai_evidence"].find(eligible_filter(db, q))}
    assert by_filter == by_rule == {evidence[0]["_id"], evidence[1]["_id"]}


# --- UC-49: anchors and context ------------------------------------------------------------------------------------


def test_text_context_keeps_whole_sentences_and_words():
    from app.evidence.context import text_context

    text = "Alpha beta gamma. Delta epsilon zeta. The excerpt sits here. Eta theta iota. Kappa lambda mu."
    start = text.index("The excerpt")
    end = start + len("The excerpt sits here.")
    context = text_context(text, start, end, pad=25)
    assert text[context["start"] : context["end"]] == "Delta epsilon zeta. The excerpt sits here. Eta theta iota."
    hindi = "पहला वाक्य यहाँ है। दूसरा वाक्य यहाँ है। सड़क टूटी हुई है। तीसरा वाक्य। चौथा वाक्य।"
    start = hindi.index("सड़क")
    context = text_context(hindi, start, start + len("सड़क टूटी हुई है।"), pad=22)
    assert hindi[context["start"] : context["end"]] == "दूसरा वाक्य यहाँ है। सड़क टूटी हुई है। तीसरा वाक्य।"
    assert text_context("only this", 0, 9) is None, "a context that adds nothing is null"
    words_only = "word " * 200
    context = text_context(words_only, 500, 510, pad=12)
    assert words_only[context["start"] : context["end"]].split() == ["word"] * 6, "no word is split"


def test_offsets_for_hindi_and_emoji_point_at_the_same_characters_in_a_browser(
    api, db, contracts, fictional, make_user
):
    from .conftest import sign_in

    text = "🙂🏠 पज़ेशन में देरी है। Quillon Residences in Sector 102: road broken 🚧, possession date unclear."
    doc = source(db, contracts, fictional, "emoji", text)
    analyst = sign_in(api, make_user, ["analyst"])
    body = api.get(f"/v1/sources/{doc['id']}/revisions/1", headers=analyst).json()
    view = body["evidence"][0]["anchor_view"]
    utf16 = text.encode("utf-16-le")
    shown = utf16[view["utf16_start"] * 2 : view["utf16_end"] * 2].decode("utf-16-le")
    assert shown == text[view["start"] : view["end"]] == body["evidence"][0]["evidence"]["excerpt_text"]
    assert view["utf16_end"] - view["end"] == 3, "three emoji take two UTF-16 units each"


def test_anchor_checks_rederive_every_excerpt(db, contracts, fictional):
    from app.evidence.anchors import anchor_problems
    from app.identity.intake import source_text

    doc = source(db, contracts, fictional, "a", POST)
    e = evidence_of(db, doc)[0]
    text = source_text(db, doc)
    assert anchor_problems(db, e, text, None) == []
    assert "excerpt hash does not match the excerpt" in anchor_problems(
        db, {**e, "excerpt_text": e["excerpt_text"] + "!"}, text, None
    )
    moved = {**e, "anchor": {**e["anchor"], "start": 1}}
    assert "the source text at the anchor is not the excerpt" in anchor_problems(db, moved, text, None)
    wide = {**e, "context_anchor": {**e["anchor"], "start": 2, "end": 9}}
    assert "context does not contain the anchor" in anchor_problems(db, wide, text, None)


def test_old_evidence_gets_its_context_once(db, contracts, fictional):
    from app.evidence.anchors import backfill_context

    long_post = "Intro about the area and the drive. " * 20 + POST + " Closing remarks about prices. " * 20
    doc = source(db, contracts, fictional, "long", long_post)
    db["ai_evidence"].update_many({}, {"$set": {"context_anchor": None}})
    first = backfill_context(db.client, db)
    assert first["looked_at"] == 1 and first["set"] + first["none_needed"] == 1
    assert backfill_context(db.client, db)["set"] == 0, "set once, never changed"
    if first["set"]:
        assert db["ai_audit_events"].count_documents({"action": "evidence.context_added"}) == 1
    assert (
        evidence_of(db, doc)[0]["context_anchor"] is None or evidence_of(db, doc)[0]["context_anchor"]["kind"] == "text"
    )


# --- UC-50: filtered retrieval -------------------------------------------------------------------------------------


ROAD = "Quillon Residences in Sector 102: the approach road is broken and floods after rain, buyers say."
LIFTS = "Quillon Residences in Sector 102: lifts are installed in Tower B and the clubhouse frame is up."
TAVIRA_ROAD = "Tavira Vista in Sector 88: the approach road is broken and floods after rain, buyers say."


def test_search_ranks_this_projects_words_and_never_another_projects(db, contracts, fictional):
    from app.evidence.retrieval import search

    q, t = fictional["Quillon Residences"], fictional["Tavira Vista"]
    road = source_for(db, contracts, q, "road", ROAD)
    source_for(db, contracts, q, "lifts", LIFTS)
    source_for(db, contracts, t, "tavira", TAVIRA_ROAD)
    result = search(db, q, "approach road floods")
    assert [i["evidence"]["source"]["id"] for i in result["items"]] == [road["id"]]
    assert all(i["evidence"]["project_id"] == q for i in result["items"]), "no other project's evidence"
    assert result["retriever"] == "keyword-v1" and result["elapsed_ms"] >= 0
    everything = search(db, q, "", limit=10)
    assert {i["evidence"]["project_id"] for i in everything["items"]} == {q} and len(everything["items"]) == 2
    assert search(db, q, "approach road", modalities=["speech"])["items"] == [], "filters come before ranking"


def test_withdrawn_or_unaccepted_evidence_leaves_retrieval_at_once_and_its_words_leave_the_index(
    db, contracts, fictional
):
    from app.evidence.retrieval import INDEX, search
    from app.sources.lifecycle import withdraw

    from .test_lifecycle import MODERATOR

    q = fictional["Quillon Residences"]
    road = source_for(db, contracts, q, "road", ROAD)
    lifts = source_for(db, contracts, q, "lifts", LIFTS)
    assert len(search(db, q, "Quillon")["items"]) == 2
    body = {"scope": "source_all_revisions", "revision": None, "reason": "Author asked"}
    withdraw(db.client, db, contracts, road["id"], body, MODERATOR)
    assert [i["evidence"]["source"]["id"] for i in search(db, q, "Quillon")["items"]] == [lifts["id"]], (
        "gone before the erase job runs"
    )
    run_jobs(db)
    assert db[INDEX].count_documents({"source.id": road["id"]}) == 0, "the search copy of the words is erased too"
    link = evidence_of(db, lifts)[0]["link_id"]
    db["ai_project_source_links"].update_one({"_id": link}, {"$set": {"status": "needs_review"}})
    assert search(db, q, "Quillon")["items"] == [], "a link in review is no support"


def test_an_english_query_reaches_hindi_speech_through_its_kept_translation(db, settings, contracts, world, video):  # noqa: F811
    from app.agents.gateway import ModelGateway
    from app.evidence.retrieval import search
    from app.media.translate import translate_segments

    from .test_gateway import FakeClient, response
    from .test_media import HINDI, FakeCaptions, process, translation_item

    settings.media_window_target_ms = 5_000
    process(db, settings, contracts, video, captions=FakeCaptions(CaptionTrack("hi", False, HINDI)))
    segments = list(db["ai_media_segments"].find({"source.id": video["id"]}).sort("time.start_ms", 1))
    for seg in segments:
        seg["text"] = db["ai_payloads"].find_one({"_id": seg["original_text_ref"]})["text"]
    items = [translation_item(segments[1]["_id"], "The clubhouse is not ready yet.", negation=True)]
    client = FakeClient(response({"outcome": "completed", "items": items}))
    translate_segments(db.client, db, ModelGateway(settings, contracts, client=client), segments, world["q"])
    found = search(db, world["q"], "clubhouse ready")
    assert [i["evidence"]["excerpt_text"] for i in found["items"]] == ["क्लबहाउस अभी तैयार नहीं है।"]
    assert search(db, world["q"], "तैयार")["items"][0]["evidence"]["language"] == "hi", "Hindi words match directly"


# --- UC-51: lineage ------------------------------------------------------------------------------------------------


def test_lineage_follows_exact_revisions_from_source_to_content(db, contracts, fictional):
    from app.evidence.lineage import affected

    doc = source(db, contracts, fictional, "a", POST)
    e = evidence_of(db, doc)[0]
    claim, finding, content = lineage_for(db, e)
    unrelated = stored(fixture("evidence.json", "claim_opinion_many_origins"))
    unrelated.update(
        id="clm_01K00000000000000000000099",
        project_id=e["project_id"],
        supporting_evidence=[{"id": e["id"], "revision": 2}],
    )
    unrelated["_id"] = "clm_01K00000000000000000000099@1"
    db["ai_claims"].insert_one(unrelated)
    lineage = affected(db, sources=[{"id": doc["id"], "revision": 1}])
    assert lineage["evidence"] == [ref(e)] and lineage["claims"] == [ref(claim)], "revision 2 of the span is not cited"
    assert lineage["findings"] == [ref(finding)]
    assert [(c["id"], c["open"]) for c in lineage["content_revisions"]] == [(content["_id"], True)]
    assert affected(db, sources=[{"id": doc["id"], "revision": 2}])["claims"] == []


def test_a_source_correction_reaches_every_draft_and_active_revision_and_withdraws_approvals(db, contracts, fictional):
    from .test_lifecycle import edited

    doc = source(db, contracts, fictional, "q", POST)
    e = evidence_of(db, doc)[0]
    _, _, approved = lineage_for(db, e, lifecycle="approved")
    _, _, draft = lineage_for(db, e, lifecycle="draft")
    edited(db, contracts, doc)  # the page was edited: revision 1 is superseded
    run_jobs(db)
    assert db["ai_content_revisions"].find_one({"_id": approved["_id"]})["lifecycle"] == "withdrawn"
    assert db["ai_content_revisions"].find_one({"_id": draft["_id"]})["lifecycle"] == "draft", "reported, not changed"
    event = db["ai_audit_events"].find_one({"action": "dependencies.invalidated", "target.id": e["link_id"]})
    details = event["details"]
    assert set(details["content_refs"].split(", ")) == {f"{approved['_id']} (approved)", f"{draft['_id']} (draft)"}
    assert details["content_withdrawn"] == approved["_id"]
    assert details["claims"] == 2 and details["findings"] == 2 and details["open_content_revisions"] == 2
    assert db["ai_audit_events"].count_documents({"action": "content_revision.withdrawn"}) == 1


def test_the_evidence_checks_pass_on_good_data_and_catch_broken_lineage(db, contracts, fictional):
    from app.evidence.retrieval import search
    from app.evidence.verify import verify_evidence

    doc = source(db, contracts, fictional, "a", POST)
    e = evidence_of(db, doc)[0]
    lineage_for(db, e)
    search(db, e["project_id"], "road")
    rows = {r["check"]: r for r in verify_evidence(db)}
    assert all(r["ok"] for r in rows.values()), [r for r in rows.values() if not r["ok"]]
    db["ai_evidence_search"].update_one({"_id": e["_id"]}, {"$set": {"text": "words the evidence never had"}})
    db["ai_claims"].update_one({}, {"$set": {"supporting_evidence": [{"id": e["id"], "revision": 7}]}})
    failed = {r["check"] for r in verify_evidence(db) if not r["ok"]}
    assert failed == {
        "the search index holds only words the evidence still has",
        "claims cite existing evidence revisions of their own project",
    }


def test_the_retrieval_benchmark_is_clean_and_reports_honestly(db, contracts, settings):
    from app.config import REPO_ROOT
    from app.evidence.benchmark import benchmark_record, run_benchmark

    result = run_benchmark(
        db.client,
        contracts,
        settings,
        REPO_ROOT / "evals" / "retrieval" / "v1",
        REPO_ROOT / "evals" / "identity" / "v1" / "catalogue.json",
    )
    assert result["unlinked_documents"] == [], "every labelled post reached its project"
    assert result["wrong_project_results"] == 0 and result["withdrawn_results"] == 0 and result["anchor_errors"] == 0
    assert result["recall_at_10_by_kind"]["same_language"] == 1.0
    assert result["recall_at_10_by_kind"]["other_word_form"] < 1.0, "no stemming in the keyword baseline"
    assert result["dataset"]["synthetic"] is True and result["scratch_database_dropped"]
    record = benchmark_record(result) | {"id": "evl_01JB0000000000000000000002", "created_at": "2026-10-05T00:00:00Z"}
    assert contracts.errors(record, "operations.schema.json#/$defs/EvaluationRun") == []


def test_new_evidence_is_clustered_by_a_scheduled_job_within_the_hour(db, contracts, fictional):
    from app.evidence.clusters import start_clustering
    from app.workers.worker import kinds_for

    assert not start_clustering(db), "nothing waiting, nothing queued"
    a = source(db, contracts, fictional, "a", POST)
    b = source(db, contracts, fictional, "b", POST)
    assert start_clustering(db) and not start_clustering(db), "one job per hour"
    assert "cluster_origins" in kinds_for("general") and "cluster_origins" not in kinds_for("media")
    run_jobs(db)
    assert cluster_of(db, a) == cluster_of(db, b) and not start_clustering(db)


def test_evidence_is_stored_with_its_context(db, settings, contracts, fictional, video):  # noqa: F811
    from .test_media import SPEECH, FakeCaptions, process

    long_post = POST + " " + "The towers look solid and the lobby is finished. " * 100
    doc = source(db, contracts, fictional, "long", long_post)
    e = evidence_of(db, doc)[0]
    assert e["anchor"]["end"] == 4000 and e["context_anchor"]["start"] == 0
    assert 4000 < e["context_anchor"]["end"] <= 4400, "the words after a capped excerpt, cut at a sentence"
    settings.media_window_target_ms = 5_000
    process(db, settings, contracts, video, captions=FakeCaptions(CaptionTrack("en", False, SPEECH)))
    speech = sorted(
        db["ai_evidence"].find({"source.id": video["id"], "modality": "speech"}), key=lambda x: x["anchor"]["start_ms"]
    )
    middle = speech[1]
    assert middle["context_anchor"]["start_ms"] == speech[0]["anchor"]["start_ms"]
    assert middle["context_anchor"]["end_ms"] >= middle["anchor"]["end_ms"]


# --- UC-52: embedding search (D51) ------------------------------------------------------------------------------------


FOLD = {"flooding": "flood", "floods": "flood", "rains": "rain", "पज़ेशन": "possession", "पानी": "water"}


class FakeEmbedder:
    """Deterministic stand-in for bge-m3: hashed words, with a few word forms and translations folded together so
    that, like the real model, "flooding" meets "floods" and "पज़ेशन" meets "possession"."""

    def __init__(self, error=None):
        self.error, self.calls, self.model = error, 0, "fake"

    def embed(self, texts):
        import hashlib
        import math

        self.calls += 1
        if self.error:
            raise self.error
        out = []
        for text in texts:
            vector = [0.0] * 1024
            for word in words(text):
                word = FOLD.get(word, word)
                vector[int(hashlib.sha256(word.encode()).hexdigest(), 16) % 1024] += 1.0
            norm = math.sqrt(sum(x * x for x in vector)) or 1.0
            out.append([x / norm for x in vector])
        return out


FLOODS = "Quillon Residences in Sector 102: the approach road floods after rain and stays under water."
HINDI_POSSESSION = "Quillon Residences Sector 102 में पज़ेशन मार्च 2027 में देने का वादा किया गया है।"


def test_vectors_find_what_keywords_miss_and_hybrid_keeps_both(db, contracts, settings, fictional):
    from app.embeddings.jobs import embed_pending
    from app.evidence.retrieval import search, sync_index

    q = fictional["Quillon Residences"]
    road = source_for(db, contracts, q, "road", FLOODS)
    hindi = source_for(db, contracts, q, "hindi", HINDI_POSSESSION)
    source_for(db, contracts, q, "lifts", LIFTS)
    source_for(db, contracts, fictional["Tavira Vista"], "tavira", TAVIRA_ROAD)
    embedder = FakeEmbedder()
    sync_index(db)
    assert embed_pending(db, embedder, settings) == {"embedded": 4, "waiting": 0}
    assert search(db, q, "flooding", embedder=embedder, mode="keyword")["items"] == [], "no stemming in keywords"
    vector = search(db, q, "flooding", embedder=embedder, mode="vector")
    assert vector["retriever"] == "vector-bge-m3-v1" and vector["items"][0]["evidence"]["source"]["id"] == road["id"]
    hybrid = search(db, q, "possession", embedder=embedder)
    assert hybrid["retriever"] == "hybrid-rrf-v1" and hybrid["degraded"] is None
    assert hybrid["items"][0]["evidence"]["source"]["id"] == hindi["id"], "an English word reaches Hindi text"
    assert all(i["evidence"]["project_id"] == q for i in hybrid["items"]), "vectors never cross projects"
    assert hybrid["items"][0]["similarity"] > 0 and "keyword_score" in hybrid["items"][0]


def test_without_the_embedder_search_falls_back_to_keywords_and_says_so(db, contracts, settings, fictional):
    from app.embeddings.client import EmbeddingUnavailable
    from app.evidence.retrieval import search

    q = fictional["Quillon Residences"]
    source_for(db, contracts, q, "road", ROAD)
    down = search(db, q, "approach road", embedder=FakeEmbedder(error=EmbeddingUnavailable("embedder: ConnectError")))
    assert down["retriever"] == "keyword-v1" and "embedder unavailable" in down["degraded"] and len(down["items"]) == 1
    none = search(db, q, "approach road", mode="vector")
    assert none["retriever"] == "keyword-v1" and "no embedder" in none["degraded"] and len(none["items"]) == 1


def test_vectors_are_made_by_a_scheduled_job_and_remade_for_a_new_model(
    db, contracts, settings, fictional, monkeypatch
):
    from app.embeddings import jobs
    from app.evidence.retrieval import INDEX

    q = fictional["Quillon Residences"]
    source_for(db, contracts, q, "road", ROAD)
    fake = FakeEmbedder()
    fake.ready = lambda: False
    monkeypatch.setattr(jobs, "default_embedder", lambda _s, **_k: fake)
    assert not jobs.start_embedding(db, settings), "nothing is queued while the embedder is down or loading"
    fake.ready = lambda: True
    assert jobs.start_embedding(db, settings) and not jobs.start_embedding(db, settings), "one job per ten minutes"
    monkeypatch.setattr(jobs, "get_settings", lambda: settings)
    run_jobs(db)
    entry = db[INDEX].find_one({"project_id": q})
    assert len(entry["embedding"]) == 1024 and entry["embedding_model"] == jobs.model_label(settings)
    settings.embedding_revision = "0" * 40  # a different pinned model: every vector is made again
    assert jobs.embed_pending(db, fake, settings)["embedded"] == 1
    erased = db["ai_evidence"].find_one({"project_id": q})
    db["ai_evidence"].update_one({"_id": erased["_id"]}, {"$set": {"excerpt_text": None}})
    from app.evidence.retrieval import sync_index

    sync_index(db, q)
    assert db[INDEX].count_documents({"project_id": q}) == 0, "no words, no vector"


def test_a_model_file_that_does_not_match_its_pinned_hash_is_refused(settings, tmp_path, monkeypatch):
    import hashlib
    import sys
    from types import SimpleNamespace

    import pytest

    from app.embeddings.model import fetch_model

    files = {"onnx/model_int8.onnx": b"weights", "tokenizer.json": b"{}"}

    def download(repo, name, revision, cache_dir):
        assert repo == settings.embedding_model and revision == settings.embedding_revision, "only the pinned commit"
        path = tmp_path / name.replace("/", "_")
        path.write_bytes(files[name])
        return str(path)

    monkeypatch.setitem(sys.modules, "huggingface_hub", SimpleNamespace(hf_hub_download=download))
    settings.embedding_sha256 = hashlib.sha256(b"weights").hexdigest()
    settings.embedding_tokenizer_sha256 = hashlib.sha256(b"{}").hexdigest()
    assert fetch_model(settings).onnx.read_bytes() == b"weights"
    files["onnx/model_int8.onnx"] = b"tampered"
    with pytest.raises(RuntimeError, match="does not match the pinned"):
        fetch_model(settings)
