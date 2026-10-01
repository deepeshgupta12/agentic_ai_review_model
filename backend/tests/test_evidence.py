"""UC-47..: the evidence layer (Step 07). Fictional catalogue only."""

from __future__ import annotations

from app.contracts import to_view
from app.evidence.clusters import cluster_origins, independent_origins
from app.evidence.similarity import normalise, words
from app.identity.intake import store_text_source
from app.identity.service import identify_source

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
