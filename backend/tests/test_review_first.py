# ruff: noqa: F811  (fixtures are imported from the collection and workflow tests)
"""Review-first fixes (D67, D68, D69): one source per person's review on portal and forum pages, Reddit through
PullPush, the reviews-only analysis and the page's review list. Synthetic pages and fictional texts only; no real
person's words or names."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from types import SimpleNamespace

import anthropic
import pytest

from app.agents.reviews import speaker_label
from app.config import REPO_ROOT
from app.connectors import portal_reviews as pr
from app.connectors import registry
from app.connectors.reddit import RedditPublic, comment_item, flatten_listing, post_item
from app.content.build import balanced

from .conftest import sign_in
from .fakenet import FakeNet
from .test_collection import coverage, internet, run_all_jobs, start, world  # noqa: F401
from .test_workflow import analysing_run, approve_all, model, work  # noqa: F401

OWNER = "We moved in after possession and the lifts work well, though the approach road still floods every monsoon."
RESIDENT = "Living here for a year now. Security is strict and the clubhouse is kept clean by the maintenance team."
LATER = "The towers look good from outside but the parking allotment took months and the help desk rarely answered."
AGENT = "Best investment in Sector 102, call me today for the lowest price and spot booking offers on every tower."
LOCALITY = "Sector 102 has good schools nearby and the expressway is close, but the market is still a drive away."
INTRO = "Quillon Residences in Sector 102, Gurgaon by Brightwell Estates: towers, floor plans and prices. " * 4
FICTIONAL_NAME = "Ravindra Fictitious"
MORE = "https://www.magicbricks.com/quillon-residences-sector-102-gurgaon-reviews-pdpid-4d4235"


def mb(review_id, text, user_type="Owner", relation="", sponsored="false"):
    return {
        "reviewId": review_id,
        "reviewDescription": text,
        "reviewTitle": "My experience",
        "userType": user_type,
        "userRelation": relation,
        "isSponsered": sponsored,
        "reviewedOn": "12/03/2026",
        "userName": FICTIONAL_NAME,
    }


def magicbricks_page(reviews, count=None, link=True):
    state = {
        "projectPageSeoStaticData": {"projectReviews": {"count": str(count or len(reviews)), "resultList": reviews}}
    }
    more = f'<p><a href="{MORE}">Read all reviews of Quillon Residences</a></p>' if link else ""
    return (
        "<html lang='en'><head><title>Quillon Residences, Sector 102, Gurgaon</title></head><body><article>"
        f"<h1>Quillon Residences</h1><p>{INTRO}</p>{more}</article>"
        f"<script>window.SERVER_PRELOADED_STATE_ = {json.dumps(state)};</script></body></html>"
    )


def ld(*items):
    return "".join(f'<script type="application/ld+json">{json.dumps(i)}</script>' for i in items)


# --- the page splitters (portal_reviews) --------------------------------------------------------------------------


def test_magicbricks_keeps_owners_residents_and_agents_and_leaves_out_sponsored_short_and_repeated():
    page = magicbricks_page(
        [
            mb("r1", OWNER),
            mb("r2", RESIDENT, user_type="Tenant", relation="Lives in Project"),
            mb("r3", AGENT, user_type="Agent", relation="Agent in Project"),
            mb("r4", LATER, sponsored="true"),
            mb("r5", "Nice project."),
            mb("r6", OWNER.upper()),
        ],
        count=9,
    )
    found = pr.page_reviews("https://www.magicbricks.com/quillon-residences-pdpid-4d4235", page, ["Quillon Residences"])
    assert [(r.key, r.role, r.role_basis, r.kind) for r in found.reviews] == [
        ("mb-r1", "owner", "platform_badge", "user_review"),
        ("mb-r2", "resident", "platform_badge", "user_review"),
        ("mb-r3", "broker", "platform_badge", "user_review"),  # kept with its badge; the moderator decides (D73)
    ]
    assert found.dropped == {"sponsored": 1, "too_short": 1, "duplicate": 1}
    assert found.reviews[0].published["value"] == "2026-03-12T00:00:00Z"
    assert found.more_url == MORE, "9 reviews, 6 listed: the full list is read once"
    assert FICTIONAL_NAME not in repr(found), "the reviewer's name is never kept"
    assert pr.magicbricks(magicbricks_page([mb("r1", OWNER)])).more_url is None


def test_99acres_keeps_the_locality_reviews_the_page_marks_up_as_the_projects_titled_as_the_localitys():
    state = {"pageData": {"localityReviews": [{"review": LOCALITY}], "other": "x"}}
    page = (
        f"<html><body><script>window.__initialData__ = {json.dumps(state)};</script>"
        + ld(
            {
                "@type": "Product",
                "name": "Quillon Residences",
                "review": [
                    {"@type": "Review", "reviewBody": LOCALITY, "author": {"name": "Resident"}},
                    {
                        "@type": "Review",
                        "reviewBody": OWNER,
                        "author": {"name": "Owner"},
                        "datePublished": "2026-02-01",
                    },
                    {"@type": "Review", "reviewBody": AGENT, "author": {"name": "Agent"}},
                    {"@type": "Review", "reviewBody": RESIDENT, "author": {"name": "Sagenta Fictitious"}},
                ],
            }
        )
        + "</body></html>"
    )
    found = pr.page_reviews("https://www.99acres.com/quillon-residences-npxid-r1", page, [])
    assert [(r.text, r.role, r.title) for r in found.reviews] == [
        (LOCALITY, "resident", pr.LOCALITY_TITLE),  # kept for the moderator to decide (D73)
        (OWNER, "owner", None),
        (AGENT, "broker", None),
        (RESIDENT, "unknown", None),
    ]
    assert found.dropped == {}
    assert found.reviews[1].published["precision"] == "day"


def test_nobroker_keeps_the_answers_not_the_question():
    question = "Is Quillon Residences in Sector 102 a good project to buy into this year? Please share."
    page = ld(
        {
            "@type": "DiscussionForumPosting",
            "headline": "Quillon Residences review",
            "text": question,
            "comment": [
                {"@type": "Comment", "text": f"<p>{OWNER}</p>", "datePublished": "2026-04-02T08:00:00Z"},
                {"@type": "Comment", "text": RESIDENT, "author": {"name": FICTIONAL_NAME}},
            ],
        }
    )
    found = pr.page_reviews("https://www.nobroker.in/forum/quillon-residences-review/", page, [])
    assert [r.text for r in found.reviews] == [OWNER, RESIDENT] and question not in repr(found)
    assert {r.kind for r in found.reviews} == {"forum_post"} and FICTIONAL_NAME not in repr(found)


def test_quora_reads_the_answers_a_signed_out_visitor_is_served():
    page = ld(
        {
            "@type": "QAPage",
            "mainEntity": {
                "@type": "Question",
                "name": "Is Quillon Residences worth buying?",
                "text": "Is Quillon Residences in Sector 102 worth buying for a family of four?",
                "acceptedAnswer": {"@type": "Answer", "text": f"<p>{OWNER}</p>", "dateCreated": "2026-05-01T10:00:00Z"},
                "suggestedAnswer": [
                    {"@type": "Answer", "text": LATER, "author": {"name": FICTIONAL_NAME}},
                    {"@type": "Answer", "text": "Yes."},
                ],
            },
        }
    )
    found = pr.page_reviews("https://www.quora.com/Is-Quillon-Residences-worth-buying", page, [])
    assert [r.text for r in found.reviews] == [OWNER, LATER] and found.dropped == {"too_short": 1}
    assert found.reviews[0].published == {
        "status": "known",
        "value": "2026-05-01T10:00:00Z",
        "precision": "instant",
        "basis": "platform_metadata",
    }
    assert "worth buying for a family" not in repr(found), "the question is not an answer"


def test_other_pages_keep_only_reviews_of_the_project():
    page = ld(
        {"@type": "Review", "itemReviewed": {"name": "Quillon Residences, Sector 102"}, "reviewBody": OWNER},
        {"@type": "Review", "itemReviewed": {"name": "Verdalia Parq"}, "reviewBody": RESIDENT},
        {"@type": "Review", "reviewBody": LATER},  # names no item: it is on the project's page
    )
    found = pr.page_reviews("https://housing.com/in/buy/projects/page/1-quillon", page, ["Quillon Residences"])
    assert [r.text for r in found.reviews] == [OWNER, LATER] and found.dropped == {"about_another_item": 1}


def test_dates_are_read_as_the_platform_states_them():
    now = datetime(2026, 10, 14, 9, 0, tzinfo=UTC)
    assert pr.dated("12/03/2026")["value"] == "2026-03-12T00:00:00Z"
    assert pr.dated("31/02/2026")["status"] == "unknown", "no such day"
    ago = pr.dated("2Y ago", now)
    assert ago["status"] == "approximate" and ago["precision"] == "year" and ago["value"].startswith("2024-10")
    assert pr.dated("2026-05-01")["precision"] == "day" and pr.dated("2026-05-01T10:00:00Z")["precision"] == "instant"
    assert pr.dated("")["status"] == pr.dated("last spring")["status"] == "unknown"


def test_a_badge_is_read_as_whole_words():
    assert pr._role_from_name("Sagenta Fictitious") == ("unknown", "none")
    assert pr._role_from_name("Verified Owner") == ("owner", "platform_badge")
    assert pr._role_from_name("Agent") == ("broker", "platform_badge")


# --- the web reader splits a portal page (collection) --------------------------------------------------------------


PROJECT_PAGE = "https://www.magicbricks.com/quillon-residences-pdpid-4d4235"


def serve(net, first, full):
    net.html(
        "www.magicbricks.com",
        {
            PROJECT_PAGE.removeprefix("https://www.magicbricks.com"): (200, first),
            MORE.removeprefix("https://www.magicbricks.com"): (200, full),
        },
    )


def portal(db, settings, world, monkeypatch):
    """A run whose Brave search finds the project's MagicBricks page: it lists two of three reviews (one by an agent)
    and links to the full list."""
    net = internet()
    net.json(
        "api.search.brave.com",
        lambda r: (200, {"query": {}, "web": {"results": [{"url": PROJECT_PAGE, "title": "Quillon"}]}}),
    )
    serve(
        net,
        magicbricks_page([mb("r1", OWNER), mb("r3", AGENT, user_type="Agent")], count=3),
        magicbricks_page(
            [mb("r1", OWNER), mb("r2", RESIDENT, relation="Lives in Project"), mb("r3", AGENT, user_type="Agent")],
            link=False,
        ),
    )
    monkeypatch.setattr(registry, "safe_client", lambda _s: net.client())
    run_id = start(db, settings, world["q"], connectors=["brave_search"])["run_id"]
    run_all_jobs(db)
    return net, run_id


def test_a_portal_page_becomes_one_source_per_review_under_it_and_a_review_on_two_pages_is_stored_once(
    db, settings, world, monkeypatch
):
    net, run_id = portal(db, settings, world, monkeypatch)
    pages = list(db["ai_sources"].find({"connector_id": "web_fetch", "source_kind": "article"}))
    reviews = {r["native_id"]: r for r in db["ai_sources"].find({"source_kind": "user_review"})}
    assert len(pages) == 2, "the project page and its full review list"
    assert set(reviews) == {
        "magicbricks.com#review-mb-r1",
        "magicbricks.com#review-mb-r2",
        "magicbricks.com#review-mb-r3",
    }, "an agent's review is kept with its badge (D73)"
    assert reviews["magicbricks.com#review-mb-r3"]["author"]["role"] == "broker"
    assert {r["parent"]["id"] for r in reviews.values()} <= {p["id"] for p in pages}
    assert reviews["magicbricks.com#review-mb-r1"]["author"] == {
        "display_name": None,
        "role": "owner",
        "role_basis": "platform_badge",
    }
    assert reviews["magicbricks.com#review-mb-r2"]["author"]["role"] == "resident"
    for review in reviews.values():
        link = db["ai_project_source_links"].find_one({"source.id": review["id"]})
        assert link["project_id"] == world["q"] and link["status"] == "auto_accepted", "it inherits its page's match"
    stored = json.dumps([str(d) for c in ("ai_sources", "ai_payloads") for d in db[c].find()])
    assert FICTIONAL_NAME not in stored.replace("\\", ""), "no reviewer name anywhere"
    note = coverage(db, run_id)["web_fetch"]["note"]
    assert "agent_written" not in note and "reviews_stored: 3" in note
    assert [r.url.path for r in net.requests].count(MORE.removeprefix("https://www.magicbricks.com")) == 1


def test_a_portal_page_is_read_again_on_the_next_run_and_its_reviews_are_not_stored_twice(
    db, settings, world, monkeypatch
):
    """D73: people add reviews to a portal page, and the rules that split it change; a page read once used to be
    never read again."""
    from .test_collection import start_again

    net, _ = portal(db, settings, world, monkeypatch)
    first = db["ai_sources"].count_documents({"source_kind": "user_review"})
    page_reads = [r.url.path for r in net.requests if r.url.host == "www.magicbricks.com"]
    second = start_again(db, settings, world["q"], connectors=["brave_search"])["run_id"]
    run_all_jobs(db)
    again = [r.url.path for r in net.requests if r.url.host == "www.magicbricks.com"]
    assert len(again) > len(page_reads), "the review pages were read again"
    assert db["ai_sources"].count_documents({"source_kind": "user_review"}) == first, "no review stored twice"
    assert db["ai_sources"].count_documents({"connector_id": "web_fetch", "source_kind": "article"}) == 2
    note = coverage(db, second)["web_fetch"]["note"]
    assert "reviews_stored: 0" in note and "already_read" not in note, note


# --- Reddit through PullPush (D67) ----------------------------------------------------------------------------------


def entry(entry_id, **fields):
    return {"id": entry_id, "created_utc": 1789000000, "permalink": f"/r/gurgaon/comments/{entry_id}/x/", **fields}


def test_reddit_keeps_people_and_no_usernames():
    from app.connectors.reddit import _skip

    assert _skip(entry("a", author="[deleted]", body="x y z"))
    assert _skip(entry("b", author="AutoModerator", body="Rules of the subreddit apply here."))
    assert _skip(entry("c", author="gurgaon_helper_bot", body="Beep boop I am a helpful automated account."))
    assert _skip(entry("d", author="mod", distinguished="moderator", body="Thread locked for now."))
    assert _skip(entry("e", author="someone", body="[removed]"))
    assert _skip(entry("f", author="someone", title="t", selftext="", removed_by_category="moderator"))
    assert not _skip(entry("g", author="someone", body=OWNER))
    post = post_item(entry("p1", author="someone", title="Quillon  Residences?", selftext=OWNER, subreddit="gurgaon"))
    assert post.native_id == "t3_p1" and post.title == "Quillon Residences? (r/gurgaon)"
    assert post.text == f"Quillon Residences?\n\n{OWNER}" and post.author["display_name"] is None
    assert post.canonical_url == "https://www.reddit.com/r/gurgaon/comments/p1/x"
    comment = comment_item(entry("c1", author="someone", body=OWNER, link_id="t3_p1"))
    assert comment.parent == {"native_id": "t3_p1"} and comment.source_kind == "comment"
    assert "someone" not in repr(post) + repr(comment)


def test_reddit_own_thread_json_is_flattened_with_every_reply():
    reply = {"kind": "t1", "data": {"id": "c2", "body": LATER, "replies": ""}}
    top = {"kind": "t1", "data": {"id": "c1", "body": OWNER, "replies": {"data": {"children": [reply]}}}}
    more = {"kind": "more", "data": {"children": ["c9"]}}
    listing = [{"data": {"children": [{"kind": "t3", "data": {"id": "p1"}}]}}, {"data": {"children": [top, more]}}]
    post, comments = flatten_listing(listing)
    assert post == {"id": "p1"} and [c["id"] for c in comments] == ["c1", "c2"]
    assert flatten_listing({"error": 403}) == (None, [])


class FakeScrapfly:
    def __init__(self, listing):
        self.listing, self.calls = listing, []

    def scrape(self, url):
        self.calls.append(url)
        return SimpleNamespace(html=json.dumps(self.listing), upstream_status=200, credits=1)


@pytest.mark.parametrize("allowance", [0, 1])
def test_a_thread_pullpush_lacks_is_read_through_scrapfly_only_within_the_allowance(db, settings, allowance):
    net = FakeNet()
    net.json("api.pullpush.io", lambda r: (200, {"data": []}))
    settings.reddit_threads_via_scrapfly_per_run = allowance
    listing = [
        {"data": {"children": [{"kind": "t3", "data": entry("p1", author="someone", title="Quillon")}]}},
        {"data": {"children": [{"kind": "t1", "data": entry("c1", author="someone", body=OWNER, replies="")}]}},
    ]
    scrapfly = FakeScrapfly(listing)
    reddit = RedditPublic(net.client(), db, settings, scrapfly)
    first = reddit.thread(entry("p1", num_comments=4), 100)
    second = reddit.thread(entry("p2", num_comments=4), 100)
    assert len(scrapfly.calls) == allowance and second.via == "pullpush" and second.comments == []
    if allowance:
        assert first.via == "scrapfly" and [c["id"] for c in first.comments] == ["c1"]
        assert scrapfly.calls == ["https://www.reddit.com/comments/p1.json"]
    assert reddit.thread(entry("p3", num_comments=0), 100).via == "pullpush", "no comments to look for"
    assert "www.reddit.com" not in net.hosts_requested(), "Reddit is never asked directly"


# --- who the review is from (A11) -----------------------------------------------------------------------------------


def test_the_speaker_comes_from_the_words_then_the_badge_then_the_platform():
    reddit = {"connector_id": "reddit_public", "author": {"role": "unknown"}}
    portal_owner = {"connector_id": "web_fetch", "author": {"role": "owner"}}
    youtube = {"connector_id": "youtube_data_api", "author": {"role": "unknown"}}
    assert speaker_label("resident_experience", "comment", reddit) == "a_resident"
    assert speaker_label("unclear", "user_review", portal_owner) == "an_owner"
    assert speaker_label("unclear", "comment", reddit) == "a_user"
    assert speaker_label("unclear", "forum_post", {"connector_id": "web_fetch", "author": None}) == "a_user"
    assert speaker_label("unclear", "comment", youtube) == "a_viewer"


# --- the reviews-only analysis (D68) --------------------------------------------------------------------------------


def test_a_reviews_only_analysis_asks_only_the_review_curator(db, settings, contracts, fictional, model):
    settings.analysis_mode = "reviews"  # the default; the `model` fixture sets full for the facts tests
    q, run = analysing_run(db, settings, contracts, fictional)
    assert work(db) == ["waiting_review"]
    assert model.calls == ["A11"], "no claims, verification or findings"
    assert db["ai_claims"].count_documents({}) == 0 and db["ai_findings"].count_documents({}) == 0
    assert db["ai_review_excerpts"].count_documents({"project_id": q, "review_status": "pending"}) == 2
    run = db["ai_runs"].find_one({"_id": run["_id"]})
    assert run["stage"] == "findings_review"
    assert db["ai_review_excerpts"].count_documents({"review_status": "approved"}) == 0, "models never approve"


# --- the page's review list (D69) ------------------------------------------------------------------------------------


def review(rid, polarity, day):
    return {"id": rid, "polarity": polarity, "published": {"value": f"2026-0{day}-01T00:00:00Z"}}


def test_the_page_list_mixes_the_sides_in_proportion_newest_first_within_its_limit():
    pool = [review(f"p{i}", "positive", i) for i in range(1, 7)]
    pool += [review(f"n{i}", "negative", i) for i in range(1, 4)] + [review("m1", "mixed", 5)]
    out = balanced(pool, 20)
    assert sorted(r["id"] for r in out) == sorted(r["id"] for r in pool)
    for k in range(1, len(out) + 1):
        for side, size in (("positive", 6), ("negative", 3), ("mixed", 1)):
            shown = sum(1 for r in out[:k] if r["polarity"] == side)
            assert abs(shown - k * size / 10) <= 1, (k, side, [r["id"] for r in out])
    assert [r["id"] for r in out if r["polarity"] == "negative"] == ["n3", "n2", "n1"], "newest first"
    capped = balanced(pool, 5)
    assert len(capped) == 5 and {r["polarity"] for r in capped} >= {"positive", "negative"}
    assert balanced([], 20) == []


def test_the_page_takes_at_most_its_limit_of_reviews_each_30_to_80_words(
    api, db, settings, contracts, fictional, model, make_user
):
    settings.analysis_mode = "reviews"
    settings.review_words_min = 20  # the published limit (the shared fixture lowers it for its short texts)
    q, _ = analysing_run(db, settings, contracts, fictional)
    work(db)
    approve_all(db, q)
    rows = list(db["ai_review_excerpts"].find({"project_id": q}))
    words = {r["id"]: len(r["text"].split()) for r in rows}
    short = next(r for r in rows if words[r["id"]] < settings.review_words_min)
    fit = next(r for r in rows if settings.review_words_min <= words[r["id"]] <= settings.review_words_max)
    moderator = sign_in(api, make_user, ["moderator"])

    def generate(selected, key):
        body = {
            "mode": "generate",
            "locale": "en-IN",
            "findings": [],
            "reviews": [{"id": r["id"], "revision": r["revision"]} for r in selected],
        }
        return api.post(f"/v1/projects/{q}/content-revisions", json=body, headers={**moderator, "Idempotency-Key": key})

    refused = generate([short, fit], "gen-words-0001")
    assert refused.status_code == 422 and "20 to 80 words" in refused.json()["error"]["message"]
    assert short["id"] in json.dumps(refused.json()["error"]["fields"])
    settings.review_words_min, settings.page_reviews_max = 1, 1
    too_many = generate([short, fit], "gen-many-0001")
    assert too_many.status_code == 422 and "at most 1 reviews" in too_many.json()["error"]["message"]
    settings.review_words_min, settings.page_reviews_max = 20, 20
    accepted = generate([fit], "gen-fits-0001")
    assert accepted.status_code == 202, accepted.text
    assert work(db) == ["completed"]
    run = db["ai_runs"].find_one({"project_id": q}, sort=[("created_at", -1)])
    revision = db["ai_content_revisions"].find_one({"_id": run["content_revision_id"]})
    assert [r["text"] for r in revision["payload"]["reviews"]] == [fit["text"]]
    assert revision["payload"]["attribution"] is None, "no line of ours on a reviews-only page (D69)"

    # An edit may add another approved review of the project (D69), within the same limits; never an unapproved one.
    def edit_adding(review, key):
        payload = json.loads(json.dumps(revision["payload"], default=str))
        extra = json.loads(json.dumps(payload["reviews"][0]))
        extra["support"]["review"] = {"id": review["id"], "revision": review["revision"]}
        payload["reviews"].append(extra)
        body = {
            "mode": "edit",
            "locale": "en-IN",
            "base": {"id": revision["_id"], "revision": revision["revision"]},
            "payload": payload,
            "reason": "add a review",
        }
        return api.post(f"/v1/projects/{q}/content-revisions", json=body, headers={**moderator, "Idempotency-Key": key})

    db["ai_review_excerpts"].update_one({"_id": short["_id"]}, {"$set": {"review_status": "pending"}})
    pending = edit_adding(short, "edit-pending-0001")
    assert pending.status_code == 409 and "pending" in pending.json()["error"]["message"]
    db["ai_review_excerpts"].update_one({"_id": short["_id"]}, {"$set": {"review_status": "approved"}})
    assert edit_adding(short, "edit-short-0001").status_code == 422, "too short for the page"
    settings.review_words_min = 1
    added = edit_adding(short, "edit-added-0001")
    assert added.status_code == 201, added.text
    new = added.json()["revision"]
    assert new["revision"] == 2 and new["lifecycle"] == "final_review" and len(new["payload"]["reviews"]) == 2
    assert {r["id"] for r in new["manifest"]["reviews"]} == {fit["id"], short["id"]}
    assert new["payload"]["reviews"][1]["text"] == short["text"], "the approved words, rebuilt by the backend"
    assert new["payload"]["metadata"]["description"].startswith("Read 2 reviews of Quillon Residences")
    assert new["payload"]["coverage_note"].startswith("2 reviews:"), "the counts the backend wrote follow the edit"


def test_a_review_is_rechecked_on_its_page_by_its_key_and_never_replaced_by_the_whole_page(
    db, settings, world, monkeypatch
):
    from .test_recheck import recheck

    net, _ = portal(db, settings, world, monkeypatch)
    changed = OWNER.replace("the lifts work well", "the lifts mostly work")
    still = magicbricks_page([mb("r1", changed), mb("r3", AGENT, user_type="Agent")], count=2, link=False)
    serve(net, still, still)  # the owner edited the review; the resident's review is no longer shown
    recheck(db)
    owner = list(db["ai_sources"].find({"native_id": "magicbricks.com#review-mb-r1"}).sort("revision", 1))
    assert [(s["revision"], s["lifecycle"]) for s in owner] == [(1, "superseded"), (2, "active")]
    assert owner[1]["parent"] == owner[0]["parent"] and owner[1]["source_kind"] == "user_review"
    link = db["ai_project_source_links"].find_one({"source.id": owner[1]["id"], "source.revision": 2})
    assert link["project_id"] == world["q"] and link["status"] == "auto_accepted", "it inherits its page's match again"
    resident = {"native_id": "magicbricks.com#review-mb-r2"}
    assert db["ai_sources"].find_one(resident)["lifecycle"] == "unavailable", "gone once"
    recheck(db)
    assert db["ai_sources"].find_one(resident)["lifecycle"] == "deleted", "gone twice"
    pages = list(db["ai_sources"].find({"connector_id": "web_fetch", "source_kind": "article"}))
    assert len(pages) == 2 and {p["revision"] for p in pages} == {1}, "no page was overwritten by a review"


def test_reddit_is_searched_only_with_names_that_stand_alone(db, settings, world, monkeypatch):
    """A context-required name ("Quillon" alone) would bring unrelated threads, each read and matched for nothing."""
    config = db["ai_project_configs"].find_one({"_id": world["q"]})
    modes = {a["text"]: a["mode"] for a in config["aliases"]}
    assert modes.get("Quillon") == "context_required", modes
    net = internet()
    monkeypatch.setattr(registry, "safe_client", lambda _s: net.client())
    start(db, settings, world["q"], connectors=["reddit_public"])
    run_all_jobs(db)
    searched = {
        r.url.params.get("q") for r in net.requests if r.url.host == "api.pullpush.io" and r.url.params.get("q")
    }
    assert '"Quillon Residences"' in searched and '"Quillon"' not in searched, searched
    standalone = {f'"{text}"' for text, mode in modes.items() if mode == "standalone"}
    assert searched <= standalone | {'"Quillon Residences"'}


# --- a cut-off answer is split, and an unfinished reading stops the run (first live run, 14 Oct 2026) -------------


def cut_off_above(model, sources_allowed):
    """The scripted model answers A11 with a cut-off reply (stop_reason max_tokens, as the real model did for 36
    sources at 4,000 tokens) whenever a task holds more than `sources_allowed` sources."""
    from .test_gateway import response

    answer = model.create

    def create(**kwargs):
        system = kwargs["system"] if isinstance(kwargs["system"], str) else kwargs["system"][0]["text"]
        lines = [x for x in kwargs["messages"][0]["content"].splitlines() if x.startswith("{")]
        if system.startswith("You are A11") and len(lines) - 1 > model.allowed:
            model.calls.append("A11")
            return response({"outcome": "completed", "reviews": []}, stop_reason="max_tokens")
        return answer(**kwargs)

    model.allowed = sources_allowed
    model.create = create


def test_a_cut_off_review_task_is_split_and_read_again(db, settings, contracts, fictional, model):
    settings.analysis_mode = "reviews"
    cut_off_above(model, 1)
    q, run = analysing_run(db, settings, contracts, fictional)
    assert work(db) == ["waiting_review"]
    assert model.calls == ["A11", "A11", "A11"], "the two-source task, then each half"
    assert db["ai_review_excerpts"].count_documents({"project_id": q}) == 2
    assert db["ai_runs"].find_one({"_id": run["_id"]})["stage"] == "findings_review"


def test_an_unfinished_reading_stops_the_run_and_continue_analysis_finishes_it(
    api, db, settings, contracts, fictional, model, make_user
):
    from .test_audit_fixes import a11_fails_with
    from .test_gateway import api_error

    settings.analysis_mode = "reviews"
    a11_fails_with(model, api_error(anthropic.BadRequestError, 400))  # a failure that cannot be split
    q, run = analysing_run(db, settings, contracts, fictional)
    work(db)
    stopped = db["ai_runs"].find_one({"_id": run["_id"]})
    assert stopped["stage"] == "analysing", "never insufficient_evidence when the reading failed"
    assert stopped["outcome_note"].startswith("Analysis stopped: reviews_unfinished")
    path = f"/v1/runs/{run['_id']}/analysis"
    moderator = sign_in(api, make_user, ["moderator"])
    assert api.post(path, headers=moderator).status_code == 403
    researcher = sign_in(api, make_user, ["researcher"])
    model.failing = False  # the cause is fixed
    accepted = api.post(path, headers=researcher)
    assert accepted.status_code == 202, accepted.text
    assert contracts.errors(accepted.json(), "api.schema.json#/$defs/Accepted") == []
    again = api.post(path, headers=researcher)
    assert again.status_code == 409 and again.json()["error"]["code"] == "invalid_transition", "one at a time"
    assert db["ai_runs"].find_one({"_id": run["_id"]})["outcome_note"].startswith("Analysis continued")
    assert work(db) == ["waiting_review"]
    assert db["ai_runs"].find_one({"_id": run["_id"]})["stage"] == "findings_review"
    assert db["ai_review_excerpts"].count_documents({"project_id": q}) == 2
    assert db["ai_audit_events"].count_documents({"action": "run.analysis_continued"}) == 1


def test_continue_analysis_is_refused_while_the_budget_has_nothing_left(
    api, db, settings, contracts, fictional, model, make_user
):
    from .test_audit_fixes import a11_fails_with
    from .test_gateway import api_error

    settings.analysis_mode = "reviews"
    a11_fails_with(model, api_error(anthropic.BadRequestError, 400))
    _, run = analysing_run(db, settings, contracts, fictional)
    work(db)
    settings.model_budget_usd = 0.0
    researcher = sign_in(api, make_user, ["researcher"])
    refused = api.post(f"/v1/runs/{run['_id']}/analysis", headers=researcher)
    assert refused.status_code == 409 and "MODEL_BUDGET_USD" in refused.json()["error"]["message"]
    assert (
        refused.json()["error"]["code"]
        in json.loads((REPO_ROOT / "contracts" / "v1" / "common.schema.json").read_text())["$defs"]["ErrorCode"]["enum"]
    )
    assert api.post("/v1/runs/run_01K0000000000000000000000Z/analysis", headers=researcher).status_code == 404


# --- live coverage while a run collects ------------------------------------------------------------------------


def test_coverage_shows_queued_then_running_then_final(db, settings, world):
    from app.sources.collection import EVENTS

    run_id = start(db, settings, world["q"])["run_id"]
    planned = coverage(db, run_id)
    assert planned["reddit_public"]["note"] == "queued" and planned["web_fetch"]["note"] == "queued"
    run_all_jobs(db)
    events = list(db[EVENTS].find({"run_id": run_id, "type": "coverage_updated"}))
    for source in ("brave_search", "web_fetch", "youtube_data_api", "reddit_public"):
        notes = [e["coverage"]["note"] or "" for e in events if e["coverage"]["connector_id"] == source]
        assert any(n.startswith("in progress: ") for n in notes), (source, notes)
    final = coverage(db, run_id)
    assert all(
        not (c["note"] or "").startswith(("in progress", "queued"))
        for c in final.values()
        if c["status"] != "access_pending"
    )


# --- portal and Quora hits are read only when they name the project ---------------------------------------------


def test_a_portal_page_of_another_project_is_not_read(db, settings, world, monkeypatch):
    from app.sources.collection import NameKeys, names_the_project
    from app.sources.store import Item

    def hit(url, title):
        return Item(
            connector_id="brave_search",
            native_id=url,
            canonical_url=url,
            source_kind="search_result",
            capture_level="metadata_only",
            title=title,
        )

    names = NameKeys(names=[["quillon", "residences"]], own=[], places=["sector 102", "gurgaon"])
    assert names_the_project(hit("https://www.magicbricks.com/quillon-residences-sector-102-pdpid-1", "Reviews"), names)
    assert names_the_project(hit("https://www.quora.com/Is-it-good", "Is Quillon Residences worth it?"), names)
    assert not names_the_project(
        hit("https://www.magicbricks.com/brightwell-towers-sector-9-pdpid-2", "Brightwell"), names
    )
    assert not names_the_project(hit("https://www.magicbricks.com/quillon-residency-pdpid-3", "x"), names), (
        "whole words"
    )
    net = internet()
    other = "https://www.magicbricks.com/brightwell-towers-sector-9-gurgaon-pdpid-4d42"
    net.json(
        "api.search.brave.com",
        lambda r: (
            200,
            {
                "query": {},
                "web": {
                    "results": [
                        {"url": PROJECT_PAGE, "title": "Quillon"},
                        {"url": other, "title": "Brightwell Towers reviews"},
                    ]
                },
            },
        ),
    )
    serve(net, magicbricks_page([mb("r1", OWNER)]), magicbricks_page([mb("r1", OWNER)], link=False))
    monkeypatch.setattr(registry, "safe_client", lambda _s: net.client())
    run_id = start(db, settings, world["q"], connectors=["brave_search"])["run_id"]
    run_all_jobs(db)
    assert "/brightwell-towers-sector-9-gurgaon-pdpid-4d42" not in [r.url.path for r in net.requests]
    assert "not_read:no_project_name_in_title_or_address: " in coverage(db, run_id)["brave_search"]["note"]
