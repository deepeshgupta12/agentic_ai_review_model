"""Transcribing and reading project videos (Step 06.1 to 06.5 and 06.7; D47, D49).

Only active videos with an accepted project link are processed. Speech takes the first route that works:
1. the published caption track (manual before auto-generated, preferred languages first): `public_captions`;
2. otherwise, for a video within the length cap, its audio transcribed locally: `public_audio_transcription`;
3. otherwise, or when the platform or network refuses, the video stays metadata-only with the reason recorded.
Frames (spoken_video_content v3, Z3): for a video within the length cap, one download at 480p or lower serves both
the speech (when there are no captions) and the sampled frames, which A03 reads for on-screen text and visible
facts. A refused or failed frame step never costs the captions: the speech is kept and the skip is audited.
Captions and Whisper output are grouped into windows on the original timeline (app.media.windows); each frame
observation is its own segment at its frame's time. Segments keep their text in the erasable payload store and are
matched to projects as speech, on-screen-text or frame evidence. Media state moves only along the contract's
media_access machine (transcribed, then analysed once frames are read); every change is audited.
"""

from __future__ import annotations

import logging
import shutil
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

from pymongo import MongoClient
from pymongo.client_session import ClientSession
from pymongo.database import Database

from app import audit
from app.agents.gateway import ModelGateway
from app.config import Settings, get_settings
from app.contracts import ContractStore, get_contracts
from app.db import run_in_transaction, utcnow
from app.identity.links import ACTIVE_STATUSES
from app.identity.service import identify_media
from app.identity.text import nfc, sha256_text
from app.ids import new_id
from app.jobs import queue
from app.media.fetch import (
    Captions,
    Download,
    Frame,
    FrameSampler,
    MediaError,
    MediaRefused,
    MediaUnavailable,
    Transcriber,
    WhisperTranscriber,
    YouTubeCaptions,
    YtDlpMedia,
    sample_frames,
)
from app.media.frames import analyse_frames
from app.media.language import frame_flags, language_tag, quality_flags
from app.media.translate import translate_segments
from app.media.windows import Cue, build_windows
from app.observability import log_event
from app.sources import policies

logger = logging.getLogger(__name__)
KIND = "process_media"
SPOKEN = "spoken_video_content"
VIDEO_KINDS = ("video", "short")
WAITING = ("discovered", "metadata_only", "access_pending", "error")
FRAMES_FROM_POLICY_VERSION = 3  # spoken_video_content v3 (product owner, 1 Oct 2026, Z3) covers frames


def eligible_videos(db: Database[dict[str, Any]], project_id: str | None = None) -> list[dict[str, Any]]:
    """Active YouTube videos with an accepted project link that have no transcript yet."""
    query: dict[str, Any] = {"status": {"$in": sorted(ACTIVE_STATUSES)}, "segment_key": "whole"}
    if project_id:
        query["project_id"] = project_id
    linked = db["ai_project_source_links"].distinct("source.id", query)
    return list(
        db["ai_sources"].find(
            {
                "id": {"$in": linked},
                "connector_id": "youtube_data_api",
                "source_kind": {"$in": list(VIDEO_KINDS)},
                "lifecycle": "active",
                "media.access_status": {"$in": list(WAITING)},
            },
            sort=[("collected_at", 1)],
        )
    )


def start_media(db: Database[dict[str, Any]], project_id: str | None, limit: int) -> dict[str, Any]:
    """Queue one process_media job per eligible video: at most one attempt per video revision per UTC day, so a
    refused video (for example, an unreachable network) can be tried again on a later day."""
    videos = eligible_videos(db, project_id)
    day = utcnow().strftime("%Y%m%d")
    queued = 0
    for video in videos[:limit]:
        key = f"{KIND}:{video['_id']}:{day}"
        _, created = queue.enqueue(db, KIND, key, project_id=project_id, max_attempts=3)
        queued += int(created)
    return {"eligible": len(videos), "queued": queued, "limit": limit}


def set_media_status(
    db: Database[dict[str, Any]],
    contracts: ContractStore,
    source: dict[str, Any],
    to: str,
    reason: str,
    session: ClientSession | None = None,
    route: str | None = None,
) -> dict[str, Any]:
    """Move the video along media_access (system); the transcript route is set only when transcribed."""
    current = source["media"]["access_status"]
    if current == to:
        return source
    if not contracts.transition_allowed("media_access", current, to, "system"):
        raise ValueError(f"media_access does not allow {current} -> {to}")
    changes: dict[str, Any] = {"media.access_status": to}
    if to in ("transcribed", "analysed"):
        changes["media.transcript_route"] = route
    result = db["ai_sources"].update_one(
        {"_id": source["_id"], "media.access_status": current}, {"$set": changes}, session=session
    )
    if result.modified_count != 1:
        raise RuntimeError("the video changed while being processed")
    audit.record(
        db,
        "media_access.changed",
        "source",
        source["id"],
        audit.SYSTEM_ACTOR,
        revision=source["revision"],
        details={"from": current, "to": to, "reason": reason[:300], "route": route},
        session=session,
    )
    media = {**source["media"], "access_status": to}
    if route is not None:
        media["transcript_route"] = route
    return {**source, "media": media}


def store_segments(
    client: MongoClient[dict[str, Any]],
    db: Database[dict[str, Any]],
    contracts: ContractStore,
    source: dict[str, Any],
    cues: list[Cue],
    *,
    route: str,
    declared_language: str | None,
    transcription: dict[str, Any],
    origin: str,
    settings: Settings,
) -> list[dict[str, Any]]:
    """Windows become media segments (text in the payload store) and the video becomes `transcribed`, together."""
    windows = build_windows(cues, target_ms=settings.media_window_target_ms, max_ms=settings.media_window_max_ms)
    method = "caption_timing" if transcription["engine"] == "platform_captions" else "transcript_segment"
    now = utcnow()
    segments: list[dict[str, Any]] = []
    for window in windows:
        segment_id = new_id("seg")
        text = nfc(window.text)
        segments.append(
            {
                "_id": segment_id,
                "source": {"id": source["id"], "revision": source["revision"]},
                "segment_key": window.key,
                "time": {
                    "kind": "time",
                    "start_ms": window.start_ms,
                    "end_ms": window.end_ms,
                    "precision": "approximate",  # a window spans several cues; a claim is somewhere inside it
                    "method": method,
                },
                "language": language_tag(text, declared_language),
                "modality": "speech",
                "transcription": transcription,
                "original_text_ref": f"{segment_id}:original",
                "translation": None,
                "quality_flags": quality_flags(window, origin=origin),
                "_text": text,
                "_created_at": now,
            }
        )

    def write(session: ClientSession) -> None:
        for seg in segments:
            text = seg["_text"]
            db["ai_payloads"].insert_one(
                {"_id": seg["original_text_ref"], "text": text, "sha256": sha256_text(text), "created_at": now},
                session=session,
            )
            db["ai_media_segments"].insert_one(
                {k: v for k, v in seg.items() if not k.startswith("_") or k == "_id"}, session=session
            )
        set_media_status(
            db, contracts, source, "transcribed", f"{len(segments)} transcript window(s)", session, route=route
        )

    run_in_transaction(client, write)
    return [{**seg, "text": seg["_text"]} for seg in segments]


def store_frame_segments(
    client: MongoClient[dict[str, Any]],
    db: Database[dict[str, Any]],
    contracts: ContractStore,
    source: dict[str, Any],
    observations: list[dict[str, Any]],
    *,
    declared_language: str | None,
) -> list[dict[str, Any]]:
    """A03's frame observations become segments at their frame's time, and the video becomes `analysed`. On-screen
    text keeps its language; a frame description is A03's English. Neither is a transcription."""
    now = utcnow()
    segments: list[dict[str, Any]] = []
    for item in observations:
        segment_id = new_id("seg")
        text = nfc(item["text"])
        on_screen = item["modality"] == "on_screen_text"
        segments.append(
            {
                "_id": segment_id,
                "source": {"id": source["id"], "revision": source["revision"]},
                "segment_key": f"f:{item['frame_ms']}:{'text' if on_screen else 'scene'}",
                "time": {
                    "kind": "time",
                    "start_ms": item["frame_ms"],
                    "end_ms": item["frame_ms"] + 1,
                    "precision": "exact",  # the sampled frame's own time on the original timeline
                    "method": "frame_sample",
                },
                "language": language_tag(text, declared_language) if on_screen else "en",
                "modality": item["modality"],
                "transcription": None,
                "original_text_ref": f"{segment_id}:original",
                "translation": None,
                "quality_flags": frame_flags(text, imagery=item["imagery"], uncertain=bool(item["uncertainty"])),
                "_text": text,
            }
        )

    def write(session: ClientSession) -> None:
        for seg in segments:
            text = seg["_text"]
            db["ai_payloads"].insert_one(
                {"_id": seg["original_text_ref"], "text": text, "sha256": sha256_text(text), "created_at": now},
                session=session,
            )
            db["ai_media_segments"].insert_one(
                {k: v for k, v in seg.items() if not k.startswith("_") or k == "_id"}, session=session
            )
        current = db["ai_sources"].find_one({"_id": source["_id"]}, session=session) or source
        set_media_status(
            db,
            contracts,
            current,
            "analysed",
            f"{len(segments)} frame observation(s)",
            session,
            route=current["media"]["transcript_route"],
        )

    run_in_transaction(client, write)
    return [{**seg, "text": seg["_text"]} for seg in segments]


def skip_frames(db: Database[dict[str, Any]], source: dict[str, Any], reason: str) -> str:
    """The speech is kept; why the frames were not read is audited."""
    audit.record(
        db,
        "media_frames.skipped",
        "source",
        source["id"],
        audit.SYSTEM_ACTOR,
        revision=source["revision"],
        details={"reason": reason[:300]},
    )
    return reason


def video_project(db: Database[dict[str, Any]], source: dict[str, Any]) -> str | None:
    link = db["ai_project_source_links"].find_one(
        {
            "source.id": source["id"],
            "source.revision": source["revision"],
            "segment_key": "whole",
            "status": {"$in": sorted(ACTIVE_STATUSES)},
        },
        sort=[("created_at", 1), ("_id", 1)],
    )
    return link["project_id"] if link else None


def process_video(
    client: MongoClient[dict[str, Any]],
    db: Database[dict[str, Any]],
    source: dict[str, Any],
    *,
    captions: Captions,
    download: Download,
    transcriber: Callable[[], Transcriber],
    settings: Settings,
    contracts: ContractStore,
    final_attempt: bool = True,
    check: Callable[[], Any] = lambda: None,
    gateway: ModelGateway | None = None,
    sampler: FrameSampler = sample_frames,
) -> dict[str, Any]:
    """One video through the route order. Returns what happened; raises MediaError to retry when attempts remain."""
    if source["lifecycle"] != "active" or source["media"]["access_status"] not in WAITING:
        return {"outcome": "skipped", "reason": f"{source['lifecycle']}, {source['media']['access_status']}"}
    policy = policies.current(db, SPOKEN)
    if policy is None or not (policy["collection_allowed"] and policy["ai_processing_allowed"]):
        return {"outcome": "skipped", "reason": "the spoken_video_content policy does not allow it"}
    if source["media"]["access_status"] == "error":
        source = set_media_status(db, contracts, source, "discovered", "retried from the start")
    if source["media"]["access_status"] in ("discovered", "metadata_only"):
        reason = f"{SPOKEN} v{policy['policy_version']} allows public captions, audio and frames (D33, D47, D49)"
        source = set_media_status(db, contracts, source, "access_pending", reason)
    video_id = source["native_id"].partition(":")[2]
    languages = [x.strip() for x in settings.media_caption_languages.split(",") if x.strip()]
    duration = source["media"].get("duration_ms")
    within_cap = duration is not None and duration <= settings.media_max_duration_seconds * 1000
    project_id = video_project(db, source)
    frames_skipped: str | None = None
    if not settings.media_frames_enabled:
        frames_skipped = "frames are switched off (MEDIA_FRAMES_ENABLED)"
    elif policy["policy_version"] < FRAMES_FROM_POLICY_VERSION:
        frames_skipped = f"{SPOKEN} v{policy['policy_version']} does not cover frames"
    elif gateway is None or not gateway.available:
        frames_skipped = "the model gateway is not configured (A03 reads the frames)"
    elif not within_cap:
        frames_skipped = f"too_long: longer than {settings.media_max_duration_seconds} s"
    elif project_id is None:
        frames_skipped = "the video has no accepted project match"
    observations: list[dict[str, Any]] = []
    try:
        check()
        track = captions.fetch(video_id, languages)
        has_captions = track is not None and bool(track.cues)
        if not has_captions and not within_cap:
            raise MediaUnavailable("too_long", f"no captions, and longer than {settings.media_max_duration_seconds} s")
        transcript = None
        if not has_captions or frames_skipped is None:
            check()
            settings.media_work_dir.mkdir(parents=True, exist_ok=True)
            workdir = Path(tempfile.mkdtemp(prefix="video-", dir=settings.media_work_dir))
            try:
                media, frames_skipped = _download(
                    db,
                    download,
                    source,
                    video_id,
                    workdir,
                    settings,
                    has_captions=has_captions,
                    frames_skipped=frames_skipped,
                )
                if media is not None and not has_captions:
                    check()
                    transcript = transcriber().transcribe(media, source.get("language"))
                if media is not None and frames_skipped is None:
                    check()
                    frames = _sample(sampler, media, workdir, settings)
                    if isinstance(frames, str):
                        frames_skipped = skip_frames(db, source, frames)
                    elif not frames:
                        frames_skipped = skip_frames(db, source, "no_frames: no frame could be sampled")
                    else:
                        check()
                        assert gateway is not None and project_id is not None
                        observations, outcome = analyse_frames(db, gateway, frames, source, project_id)
                        if outcome == "failed":
                            frames_skipped = skip_frames(db, source, "a03_failed: the frame analysis did not complete")
            finally:
                shutil.rmtree(workdir, ignore_errors=True)  # the audio, the video and the frames are never kept
        if has_captions:
            assert track is not None
            transcription = {
                "engine": "platform_captions",
                "model_size": None,
                "language_hint": None,
                "caption_kind": "auto_generated" if track.generated else "manual",
            }
            segments = store_segments(
                client,
                db,
                contracts,
                source,
                track.cues,
                route="public_captions",
                declared_language=track.language,
                transcription=transcription,
                origin="auto_captions" if track.generated else "manual_captions",
                settings=settings,
            )
        else:
            assert transcript is not None
            transcription = {
                "engine": "faster-whisper",
                "model_size": transcript.model_size,
                "language_hint": source.get("language"),
                "caption_kind": None,
            }
            segments = store_segments(
                client,
                db,
                contracts,
                source,
                transcript.cues,
                route="public_audio_transcription",
                declared_language=transcript.language,
                transcription=transcription,
                origin="speech_to_text",
                settings=settings,
            )
        if frames_skipped is None:
            declared = track.language if has_captions and track is not None else source.get("language")
            segments += store_frame_segments(client, db, contracts, source, observations, declared_language=declared)
    except (MediaRefused, MediaUnavailable) as exc:
        set_media_status(db, contracts, source, "metadata_only", f"{exc.code}: {exc.message}")
        return {"outcome": "metadata_only", "reason": exc.code}
    except MediaError as exc:
        if not final_attempt:
            raise
        set_media_status(db, contracts, source, "error", f"gave up after retries: {exc}")
        return {"outcome": "error", "reason": str(exc)[:200]}
    status = "analysed" if frames_skipped is None else "transcribed"
    result: dict[str, Any] = {
        "outcome": status,
        "segments": sum(1 for s in segments if s["modality"] == "speech"),
        "frame_segments": sum(1 for s in segments if s["modality"] != "speech"),
        "frames_skipped": frames_skipped,
        "links": 0,
    }
    if not segments:
        return result
    report = identify_media(client, db, source, segments, policies.ref_of(policy))
    result["links"] = len(report["links"])
    linked = next((lk["project_id"] for lk in report["links"] if lk["status"] in ACTIVE_STATUSES), None)
    if gateway is not None and linked is not None:
        readable = [s for s in segments if s["modality"] in ("speech", "on_screen_text")]
        result["translation"] = translate_segments(client, db, gateway, readable, linked)
    return result


def _download(
    db: Database[dict[str, Any]],
    download: Download,
    source: dict[str, Any],
    video_id: str,
    workdir: Path,
    settings: Settings,
    *,
    has_captions: bool,
    frames_skipped: str | None,
) -> tuple[Path | None, str | None]:
    """(the downloaded file or None, why frames are skipped). With captions, a refusal only costs the frames.
    Without captions, a video too large to fetch at 480p falls back to its audio, and a refusal stops the video."""
    with_video = frames_skipped is None

    def fetch(video: bool) -> Path:
        return download.fetch(
            video_id,
            workdir,
            max_seconds=settings.media_max_duration_seconds,
            max_bytes=settings.media_max_video_bytes if video else settings.media_max_audio_bytes,
            with_video=video,
        )

    try:
        return fetch(with_video), frames_skipped
    except MediaRefused as exc:
        if not has_captions:
            raise
        return None, skip_frames(db, source, f"{exc.code}: {exc.message}")
    except MediaUnavailable as exc:
        reason = skip_frames(db, source, f"{exc.code}: {exc.message}") if with_video else frames_skipped
        if has_captions:
            return None, reason
        if not with_video:
            raise
        return fetch(False), reason


def _sample(sampler: FrameSampler, media: Path, workdir: Path, settings: Settings) -> list[Frame] | str:
    """The sampled frames, or why there are none (an audio-only file, for example)."""
    try:
        return sampler(media, workdir, max_frames=settings.media_frames_per_video, width=settings.media_frame_width)
    except MediaUnavailable as exc:
        return f"{exc.code}: {exc.message}"


def handle_process_media(db: Database[dict[str, Any]], job: dict[str, Any], check: Any) -> str | None:
    """Worker handler for `process_media` jobs (the media worker only)."""
    settings, contracts = get_settings(), get_contracts()
    ref = job["logical_key"].split(":")[1]  # process_media:<source id>@<revision>:<day>
    source = db["ai_sources"].find_one({"_id": ref})
    if source is None:
        return None
    result = process_video(
        db.client,
        db,
        source,
        captions=YouTubeCaptions(),
        download=YtDlpMedia(),
        transcriber=lambda: WhisperTranscriber(
            settings.whisper_model,
            settings.whisper_compute_type,
            settings.whisper_models_dir,
            settings.media_max_duration_seconds,
        ),
        settings=settings,
        contracts=contracts,
        final_attempt=job["attempts"] >= job["max_attempts"],
        check=check,
        gateway=ModelGateway(settings, contracts),
    )
    log_event(logger, "video processed", source=ref, **{k: v for k, v in result.items() if k != "reason"})
    return None
