"""UC-41..UC-45: video transcripts (Step 06; D47). Fake caption, audio and Whisper adapters; fictional projects."""

from __future__ import annotations

from itertools import pairwise
from pathlib import Path

import pytest

from app.contracts import to_view
from app.identity.links import decide_link
from app.media import pipeline
from app.media.fetch import CaptionTrack, MediaError, MediaRefused, Transcript
from app.media.language import language_tag, quality_flags
from app.media.windows import Cue, Window, build_windows, window_at
from app.sources.lifecycle import withdraw
from app.workers.worker import kinds_for, run_one

from .test_collection import MODERATOR, run_all_jobs, start, world  # noqa: F401  (world is a fixture)

# --- UC-41: windows on the original timeline ---------------------------------------------------------------------


def test_cues_group_into_windows_without_moving_any_word():
    cues = [Cue(i * 5000, i * 5000 + 4000, f"line {i}") for i in range(14)]  # 70 s of speech
    cues.insert(7, Cue(35_000, 39_000, "  extra   spaces  "))
    windows = build_windows(cues, target_ms=30_000, max_ms=45_000, gap_ms=2_500)
    assert len(windows) >= 2 and all(w.end_ms - w.start_ms <= 45_000 for w in windows)
    joined = " ".join(w.text for w in windows)
    assert joined.split() == " ".join(c.text for c in sorted(cues, key=lambda c: c.start_ms)).split()
    assert all(a.end_ms <= b.start_ms for a, b in pairwise(windows)), "windows never overlap"


def test_a_long_pause_closes_a_window_and_overlapping_captions_are_clipped():
    cues = [Cue(0, 4000, "one"), Cue(3000, 9000, "two"), Cue(20_000, 22_000, "after a pause")]
    windows = build_windows(cues, target_ms=30_000, max_ms=45_000, gap_ms=2_500)
    assert [w.text for w in windows] == ["one two", "after a pause"]
    assert windows[0].end_ms <= windows[1].start_ms
    rolling = build_windows([Cue(0, 6_000, "a"), Cue(5_000, 8_000, "b")], target_ms=5_000, max_ms=45_000)
    assert [w.text for w in rolling] == ["a", "b"] and rolling[0].end_ms == 5_000 <= rolling[1].start_ms


def test_a_timestamp_jump_lands_in_the_window_that_holds_those_words():
    cues = [Cue(i * 10_000, i * 10_000 + 9_000, f"part {i}") for i in range(9)]
    windows = build_windows(cues, target_ms=30_000, max_ms=45_000)
    for ms, word in ((0, "part 0"), (41_000, "part 4"), (85_000, "part 8")):
        window = window_at(windows, ms)
        assert window is not None and word in window.text and window.start_ms <= ms < window.end_ms
    assert window_at(windows, 10_000_000) is None


# --- UC-42: language tags and quality flags ----------------------------------------------------------------------


def test_language_tags_keep_script_and_declared_language():
    assert language_tag("यह प्रोजेक्ट बहुत अच्छा है", "hi") == "hi"
    assert language_tag("ye project bahut accha hai", "hi") == "hi-Latn"
    assert language_tag("The towers look ready", "en") == "en"
    assert language_tag("", None) == "und"


def test_flags_mark_code_switching_numbers_music_and_low_confidence():
    mixed = Window(0, 30_000, "यह flat 3 BHK है और price 1.75 crore बताया", [Cue(0, 30_000, "x")])
    assert {"code_switching", "numbers_uncertain", "auto_generated_captions"} <= set(
        quality_flags(mixed, origin="auto_captions")
    )
    assert "numbers_uncertain" in quality_flags(mixed, origin="speech_to_text"), "machine-made numbers need a check"
    assert "numbers_uncertain" not in quality_flags(mixed, origin="manual_captions"), "people typed these"
    hindi = Window(0, 9_000, "एक करोड़ पच्चहेतर लाख", [Cue(0, 9_000, "x")])
    assert "numbers_uncertain" in quality_flags(hindi, origin="speech_to_text"), "Hindi number words count"
    music = Window(0, 9_000, "[Music] [Music]", [Cue(0, 4_000, "[Music]"), Cue(4_000, 9_000, "[Music]")])
    assert "music" in quality_flags(music, origin="manual_captions")
    unsure = Window(0, 9_000, "possession in 2027", [Cue(0, 9_000, "possession in 2027", -1.4, 0.1)])
    assert {"low_confidence", "numbers_uncertain"} <= set(quality_flags(unsure, origin="manual_captions"))


# --- fakes -------------------------------------------------------------------------------------------------------

SPEECH = [
    Cue(0, 9_000, "Welcome to this site visit."),
    Cue(9_000, 20_000, "The lifts are installed and the clubhouse is ready."),
    Cue(20_000, 31_000, "Possession is promised for March 2027."),
    Cue(40_000, 50_000, "Compare it with Tavira Vista in Sector 88, which has better finishing."),
    Cue(50_000, 58_000, "That one costs more per square foot."),
]


class FakeCaptions:
    def __init__(self, track=None, error=None):
        self.track, self.error, self.calls = track, error, 0

    def fetch(self, video_id, languages):
        self.calls += 1
        if self.error:
            raise self.error
        return self.track


class FakeAudio:
    def __init__(self, error=None):
        self.error, self.calls, self.workdirs = error, 0, []

    def fetch(self, video_id, workdir, *, max_seconds, max_bytes):
        self.calls += 1
        self.workdirs.append(workdir)
        if self.error:
            raise self.error
        wav = Path(workdir) / "audio.wav"
        wav.write_bytes(b"RIFF fake")
        return wav


class FakeWhisper:
    def transcribe(self, wav, language_hint):
        return Transcript("en", 0.98, "small", [Cue(c.start_ms, c.end_ms, c.text, -0.3, 0.05) for c in SPEECH])


@pytest.fixture
def video(db, settings, world, tmp_path):  # noqa: F811
    settings.media_work_dir = tmp_path / "media"
    start(db, settings, world["q"])
    run_all_jobs(db)
    source = db["ai_sources"].find_one({"source_kind": "video"})
    link = db["ai_project_source_links"].find_one({"source.id": source["id"], "segment_key": "whole"})
    assert link["status"] == "auto_accepted" and source["media"]["access_status"] == "metadata_only"
    return source


def process(db, settings, contracts, source, *, captions=None, audio=None, final_attempt=True):
    return pipeline.process_video(
        db.client,
        db,
        db["ai_sources"].find_one({"_id": source["_id"]}),
        captions=captions or FakeCaptions(),
        audio=audio or FakeAudio(),
        transcriber=FakeWhisper,
        settings=settings,
        contracts=contracts,
        final_attempt=final_attempt,
    )


def media(db, source):
    return db["ai_sources"].find_one({"_id": source["_id"]})["media"]


# --- UC-43: routes and access states -----------------------------------------------------------------------------


def test_captions_come_first_and_become_segments_on_the_original_timeline(db, settings, contracts, video):
    track = CaptionTrack("en", generated=True, cues=SPEECH)
    audio = FakeAudio()
    result = process(db, settings, contracts, video, captions=FakeCaptions(track), audio=audio)
    assert result["outcome"] == "transcribed" and audio.calls == 0, "no audio when a caption track exists"
    info = media(db, video)
    assert info["access_status"] == "transcribed" and info["transcript_route"] == "public_captions"
    segments = list(db["ai_media_segments"].find({"source.id": video["id"]}).sort("time.start_ms", 1))
    assert len(segments) == 2 and segments[0]["time"]["method"] == "caption_timing"
    for seg in segments:
        assert contracts.errors(to_view(seg), "sources.schema.json#/$defs/MediaSegment") == []
        assert db["ai_payloads"].find_one({"_id": seg["original_text_ref"]})["text"]
        assert seg["transcription"]["caption_kind"] == "auto_generated"
        assert "auto_generated_captions" in seg["quality_flags"]
    assert (
        "Possession is promised for March 2027."
        in db["ai_payloads"].find_one({"_id": segments[0]["original_text_ref"]})["text"]
    )
    changes = [e["details"]["to"] for e in db["ai_audit_events"].find({"action": "media_access.changed"})]
    assert changes == ["access_pending", "transcribed"]


def test_without_captions_the_audio_is_transcribed_locally_and_then_deleted(db, settings, contracts, video):
    audio = FakeAudio()
    result = process(db, settings, contracts, video, audio=audio)
    assert result["outcome"] == "transcribed" and audio.calls == 1
    assert media(db, video)["transcript_route"] == "public_audio_transcription"
    seg = db["ai_media_segments"].find_one({"source.id": video["id"]})
    assert seg["transcription"] == {
        "engine": "faster-whisper",
        "model_size": "small",
        "language_hint": video.get("language"),
        "caption_kind": None,
    }
    assert seg["time"]["method"] == "transcript_segment"
    assert not any(Path(w).exists() for w in audio.workdirs), "the audio is never kept"


def test_a_refusal_is_recorded_not_worked_around(db, settings, contracts, video):
    captions = FakeCaptions(error=MediaRefused("network_refused", "the connection to YouTube was refused"))
    audio = FakeAudio()
    result = process(db, settings, contracts, video, captions=captions, audio=audio)
    assert result == {"outcome": "metadata_only", "reason": "network_refused"} and audio.calls == 0
    assert media(db, video)["access_status"] == "metadata_only" and media(db, video)["transcript_route"] is None
    assert db["ai_media_segments"].count_documents({}) == 0
    assert db["ai_evidence"].count_documents({"modality": "speech"}) == 0, "no spoken evidence without a transcript"
    event = db["ai_audit_events"].find_one({"action": "media_access.changed", "details.to": "metadata_only"})
    assert "network_refused" in event["details"]["reason"]


def test_a_long_video_without_captions_is_not_downloaded(db, settings, contracts, video):
    settings.media_max_duration_seconds = 60  # the fake video lasts 9 minutes
    audio = FakeAudio()
    result = process(db, settings, contracts, video, audio=audio)
    assert result["reason"] == "too_long" and audio.calls == 0


def test_temporary_failures_retry_then_end_in_error_and_can_start_again(db, settings, contracts, video):
    broken = FakeCaptions(error=MediaError("timeout"))
    with pytest.raises(MediaError):
        process(db, settings, contracts, video, captions=broken, final_attempt=False)
    assert process(db, settings, contracts, video, captions=broken)["outcome"] == "error"
    assert media(db, video)["access_status"] == "error"
    track = CaptionTrack("en", generated=False, cues=SPEECH)
    assert process(db, settings, contracts, video, captions=FakeCaptions(track))["outcome"] == "transcribed"
    changes = [e["details"]["to"] for e in db["ai_audit_events"].find({"action": "media_access.changed"})]
    assert changes == ["access_pending", "error", "discovered", "access_pending", "transcribed"]


# --- UC-44: speech evidence and project matching ------------------------------------------------------------------


def test_windows_inherit_the_videos_match_and_a_named_project_gets_its_own(db, settings, contracts, video, world):  # noqa: F811
    process(db, settings, contracts, video, captions=FakeCaptions(CaptionTrack("en", False, SPEECH)))
    links = list(db["ai_project_source_links"].find({"source.id": video["id"], "segment_key": {"$regex": "^t:"}}))
    by_project = {}
    for link in links:
        by_project.setdefault(link["project_id"], []).append(link)
    tavira = world["fictional"]["Tavira Vista"]
    assert (
        by_project[world["q"]][0]["status"] == "auto_accepted" and by_project[world["q"]][0]["match"]["signals"] == []
    )
    assert by_project[tavira][0]["match"]["signals"], "the comparison window is matched on its own words"
    tavira_window = by_project[tavira][0]["segment_key"]
    assert tavira_window not in {lk["segment_key"] for lk in by_project[world["q"]]}, "it inherits nothing"
    for link in links:
        if link["status"] == "rejected":
            continue
        evidence = db["ai_evidence"].find_one({"link_id": link["_id"]})
        assert evidence["modality"] == "speech" and evidence["anchor"]["kind"] == "time"
        assert evidence["policy"]["family"] == "spoken_video_content"
        assert (
            contracts.errors(
                to_view(evidence, id_field=None) | {"id": evidence["id"]}, "evidence.schema.json#/$defs/Evidence"
            )
            == []
        )


def test_undoing_the_videos_match_sends_inherited_windows_back_to_review(db, settings, contracts, video, world):  # noqa: F811
    process(db, settings, contracts, video, captions=FakeCaptions(CaptionTrack("en", False, SPEECH)))
    parent = db["ai_project_source_links"].find_one({"source.id": video["id"], "segment_key": "whole"})
    body = {
        "action": "reject",
        "expected_version": parent["version"],
        "reason": "wrong project",
        "split_segments": None,
        "remap_project_id": None,
        "phase_rera_id": None,
    }
    decide_link(db.client, db, contracts, parent["_id"], body, MODERATOR)
    inherited = db["ai_project_source_links"].find_one(
        {"source.id": video["id"], "project_id": world["q"], "segment_key": {"$regex": "^t:"}}
    )
    assert inherited["status"] == "needs_review"


def test_withdrawing_a_video_erases_its_transcript(db, settings, contracts, video):
    process(db, settings, contracts, video, captions=FakeCaptions(CaptionTrack("en", False, SPEECH)))
    refs = [s["original_text_ref"] for s in db["ai_media_segments"].find({"source.id": video["id"]})]
    body = {"scope": "source_revision", "revision": 1, "reason": "creator asked"}
    withdraw(db.client, db, contracts, video["id"], body, MODERATOR)
    run_all_jobs(db)
    assert db["ai_payloads"].count_documents({"_id": {"$in": refs}}) == 0
    assert db["ai_evidence"].count_documents({"source.id": video["id"], "excerpt_text": {"$ne": None}}) == 0
    assert db["ai_media_segments"].count_documents({"source.id": video["id"]}) == len(refs), "timing stays"


# --- UC-45: which videos, which worker ------------------------------------------------------------------------------


def test_only_videos_with_an_accepted_match_are_queued_once(db, settings, video):
    assert pipeline.start_media(db, None, 10) == {"eligible": 1, "queued": 1, "limit": 10}
    assert pipeline.start_media(db, None, 10)["queued"] == 0, "one attempt per video revision per day"
    job = db["ai_jobs"].find_one({"kind": "process_media"})
    assert job["logical_key"] == f"process_media:{video['_id']}:{job['created_at']:%Y%m%d}"
    db["ai_project_source_links"].update_many({"source.id": video["id"]}, {"$set": {"status": "needs_review"}})
    assert pipeline.eligible_videos(db) == []


def test_the_media_worker_takes_only_media_jobs(db, video):
    pipeline.start_media(db, None, 10)
    assert "process_media" not in kinds_for("general") and kinds_for("media") == ["process_media"]
    assert run_one(db, "general-worker", 60, kinds_for("general")) is None, "the general worker leaves it"
    assert db["ai_jobs"].find_one({"kind": "process_media"})["status"] == "queued"


def test_duration_alone_does_not_make_a_short(db, video):
    info = media(db, video)
    assert info["format"] == "unknown" and info["format_basis"] == "unknown"


def test_the_media_library_lists_each_video_with_its_state_and_segments(
    api,
    db,
    settings,
    contracts,
    make_user,
    video,
    world,  # noqa: F811
):
    from .conftest import sign_in

    analyst = sign_in(api, make_user, ["analyst"])
    url = f"/v1/projects/{world['q']}/media"
    before = api.get(url, headers=analyst)
    assert before.status_code == 200 and contracts.errors(before.json(), "api.schema.json#/$defs/MediaPage") == []
    [item] = before.json()["items"]
    assert item["source"]["media"]["access_status"] == "metadata_only" and item["segments"] == []
    process(db, settings, contracts, video, captions=FakeCaptions(CaptionTrack("en", False, SPEECH)))
    after = api.get(url, headers=analyst).json()
    assert contracts.errors(after, "api.schema.json#/$defs/MediaPage") == []
    [item] = after["items"]
    assert item["source"]["media"]["access_status"] == "transcribed" and len(item["segments"]) == 2
    assert [s["time"]["start_ms"] for s in item["segments"]] == sorted(s["time"]["start_ms"] for s in item["segments"])
    assert api.get(f"{url}?access_status=metadata_only", headers=analyst).json()["items"] == []
    assert len(api.get(f"{url}?access_status=transcribed", headers=analyst).json()["items"]) == 1
    assert api.get(f"{url}?format=sideways", headers=analyst).status_code == 422


# --- UC-46: A04 translation with backend checks ------------------------------------------------------------------

HINDI = [
    Cue(0, 9_000, "पज़ेशन मार्च 2027 में मिलने का वादा है।"),
    Cue(9_000, 18_000, "क्लबहाउस अभी तैयार नहीं है।"),
    Cue(40_000, 49_000, "तीन बीएचके की कीमत 1.75 करोड़ है।"),
]


def translation_item(segment_id, text, negation=False, terms=()):
    return {
        "input_id": segment_id,
        "language": "hi",
        "normalised_text": "x",
        "translation": {"language": "en", "text": text},
        "negation": negation,
        "uncertainty": False,
        "possible_sarcasm": False,
        "preserved_terms": list(terms),
    }


def test_a04_translations_are_kept_only_when_numbers_and_negations_survive(db, settings, contracts, video, world):  # noqa: F811
    from app.agents.gateway import ModelGateway
    from app.media.translate import translate_segments

    from .test_gateway import FakeClient, response

    settings.media_window_target_ms = 5_000  # one window per sentence, to translate each separately
    process(db, settings, contracts, video, captions=FakeCaptions(CaptionTrack("hi", False, HINDI)))
    segments = list(db["ai_media_segments"].find({"source.id": video["id"]}).sort("time.start_ms", 1))
    assert len(segments) == 3
    for seg in segments:
        seg["text"] = db["ai_payloads"].find_one({"_id": seg["original_text_ref"]})["text"]
    good, lost_negation, lost_number = (s["_id"] for s in segments)
    items = [
        translation_item(good, "Possession is promised in March 2027.", terms=["March 2027"]),
        translation_item(lost_negation, "The clubhouse is ready now."),
        translation_item(lost_number, "A 3 BHK costs about 1.5 crore.", terms=["3 BHK"]),
        translation_item("seg_01K0000000000000000000000Z", "invented"),
    ]
    client = FakeClient(response({"outcome": "completed", "items": items}))
    gateway = ModelGateway(settings, contracts, client=client, sleep=lambda _s: None)
    report = translate_segments(db.client, db, gateway, segments, world["q"])
    assert report["kept"] == 1 and report["rejected"] == 2 and report["calls"] == 1
    kept = db["ai_media_segments"].find_one({"_id": good})
    assert kept["translation"] == {"language": "en", "text_ref": f"{good}:en", "method": "language_agent"}
    assert db["ai_payloads"].find_one({"_id": f"{good}:en"})["text"] == "Possession is promised in March 2027."
    assert db["ai_payloads"].find_one({"_id": kept["original_text_ref"]})["text"].startswith("पज़ेशन"), "original kept"
    for seg_id in (lost_negation, lost_number):
        assert db["ai_media_segments"].find_one({"_id": seg_id})["translation"] is None
    reasons = sorted(e["details"]["reason"] for e in db["ai_audit_events"].find({"action": "translation.rejected"}))
    assert reasons[0].startswith("numbers missing") and "1.75" in reasons[0]
    assert reasons[1].startswith("the original has a negation")
    run = db["ai_agent_runs"].find_one({"agent": "A04_language_context"})
    assert run["outcome"] == "completed" and len(run["input_refs"]) == 3 and run["project_id"] == world["q"]
    user_message = client.calls[0]["messages"][0]["content"]
    assert "untrusted" in user_message and "seg_01K0000000000000000000000Z" not in user_message


def test_english_windows_are_not_sent_for_translation(db, settings, contracts, video, world):  # noqa: F811
    from app.agents.gateway import ModelGateway
    from app.media.translate import translate_segments

    from .test_gateway import FakeClient

    process(db, settings, contracts, video, captions=FakeCaptions(CaptionTrack("en", False, SPEECH)))
    segments = [{**s, "text": "x"} for s in db["ai_media_segments"].find({"source.id": video["id"]})]
    client = FakeClient()
    report = translate_segments(db.client, db, ModelGateway(settings, contracts, client=client), segments, world["q"])
    assert report["considered"] == 0 and client.calls == []


def test_negation_markers_respect_devanagari_word_edges():
    from app.media.translate import NEGATION_SOURCE

    assert not NEGATION_SOURCE.search("तीन बीएचके फ्लैट की कीमत एक करोड़ है।"), "कीमत (price) ends in मत but is no negation"
    assert NEGATION_SOURCE.search("क्लबहाउस तैयार नहीं है") and NEGATION_SOURCE.search("वहाँ मत जाओ")
    assert NEGATION_SOURCE.search("abhi ready nahi hai") and not NEGATION_SOURCE.search("dekho na kitna accha hai")
    assert NEGATION_SOURCE.search("The road is not complete")


def test_the_collection_checks_accept_transcripts_and_catch_broken_ones(db, settings, contracts, video):
    from app.sources.verify import verify_collection

    process(db, settings, contracts, video, captions=FakeCaptions(CaptionTrack("en", False, SPEECH)))
    rows = {r["check"]: r for r in verify_collection(db, settings)}
    assert all(r["ok"] for r in rows.values()), [r for r in rows.values() if not r["ok"]]
    assert rows["speech evidence is governed by the spoken-content policy"]["looked_at"] > 0
    segment = db["ai_media_segments"].find_one({"source.id": video["id"]})
    db["ai_payloads"].delete_one({"_id": segment["original_text_ref"]})
    db["ai_evidence"].update_one(
        {"modality": "speech"}, {"$set": {"policy": {"family": "youtube", "policy_version": 2}}}
    )
    db["ai_sources"].update_one({"_id": video["_id"]}, {"$set": {"media.access_status": "metadata_only"}})
    failed = {r["check"] for r in verify_collection(db, settings) if not r["ok"]}
    assert failed == {
        "no evidence comes from a metadata-only record",
        "transcript segments exist only for transcribed videos",
        "every transcript window keeps its words unless its video was erased",
        "speech evidence is governed by the spoken-content policy",
    }


def test_media_state_changes_follow_the_contract(db, settings, contracts, video):
    process(db, settings, contracts, video, captions=FakeCaptions(CaptionTrack("en", False, SPEECH)))
    transcribed = db["ai_sources"].find_one({"_id": video["_id"]})
    with pytest.raises(ValueError):
        pipeline.set_media_status(db, contracts, transcribed, "metadata_only", "not allowed by media_access")
    assert media(db, video)["access_status"] == "transcribed"
