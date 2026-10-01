"""Transcribing project videos (Step 06.1 to 06.4 and 06.7; D47).

Only active videos with an accepted project link are processed. The route is chosen per video:
1. the published caption track (manual before auto-generated, preferred languages first): `public_captions`;
2. otherwise, for a video within the length cap, its audio transcribed locally: `public_audio_transcription`;
3. otherwise, or when the platform or network refuses, the video stays metadata-only with the reason recorded.
Captions and Whisper output are grouped into windows on the original timeline (app.media.windows), stored as media
segments with their text in the erasable payload store, then matched to projects as speech evidence. Media state
moves only along the contract's media_access machine; every change is audited.
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
    Audio,
    Captions,
    MediaError,
    MediaRefused,
    MediaUnavailable,
    Transcriber,
    WhisperTranscriber,
    YouTubeCaptions,
    YtDlpAudio,
)
from app.media.language import language_tag, quality_flags
from app.media.translate import translate_segments
from app.media.windows import Cue, build_windows
from app.observability import log_event
from app.sources import policies

logger = logging.getLogger(__name__)
KIND = "process_media"
SPOKEN = "spoken_video_content"
VIDEO_KINDS = ("video", "short")
WAITING = ("discovered", "metadata_only", "access_pending", "error")


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


def process_video(
    client: MongoClient[dict[str, Any]],
    db: Database[dict[str, Any]],
    source: dict[str, Any],
    *,
    captions: Captions,
    audio: Audio,
    transcriber: Callable[[], Transcriber],
    settings: Settings,
    contracts: ContractStore,
    final_attempt: bool = True,
    check: Callable[[], Any] = lambda: None,
    gateway: ModelGateway | None = None,
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
        reason = f"{SPOKEN} v{policy['policy_version']} allows public captions and audio (D33, D47)"
        source = set_media_status(db, contracts, source, "access_pending", reason)
    video_id = source["native_id"].partition(":")[2]
    languages = [x.strip() for x in settings.media_caption_languages.split(",") if x.strip()]
    try:
        check()
        track = captions.fetch(video_id, languages)
        if track is not None and track.cues:
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
            duration = source["media"].get("duration_ms")
            if duration is None or duration > settings.media_max_duration_seconds * 1000:
                raise MediaUnavailable(
                    "too_long", f"no captions, and longer than {settings.media_max_duration_seconds} s"
                )
            check()
            settings.media_work_dir.mkdir(parents=True, exist_ok=True)
            workdir = Path(tempfile.mkdtemp(prefix="video-", dir=settings.media_work_dir))
            try:
                wav = audio.fetch(
                    video_id,
                    workdir,
                    max_seconds=settings.media_max_duration_seconds,
                    max_bytes=settings.media_max_audio_bytes,
                )
                check()
                transcript = transcriber().transcribe(wav, source.get("language"))
            finally:
                shutil.rmtree(workdir, ignore_errors=True)  # the audio is never kept
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
    except (MediaRefused, MediaUnavailable) as exc:
        set_media_status(db, contracts, source, "metadata_only", f"{exc.code}: {exc.message}")
        return {"outcome": "metadata_only", "reason": exc.code}
    except MediaError as exc:
        if not final_attempt:
            raise
        set_media_status(db, contracts, source, "error", f"gave up after retries: {exc}")
        return {"outcome": "error", "reason": str(exc)[:200]}
    if not segments:
        return {"outcome": "transcribed", "segments": 0, "links": 0}
    report = identify_media(client, db, source, segments, policies.ref_of(policy))
    result: dict[str, Any] = {"outcome": "transcribed", "segments": len(segments), "links": len(report["links"])}
    project_id = next((lk["project_id"] for lk in report["links"] if lk["status"] in ACTIVE_STATUSES), None)
    if gateway is not None and project_id is not None:
        result["translation"] = translate_segments(client, db, gateway, segments, project_id)
    return result


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
        audio=YtDlpAudio(),
        transcriber=lambda: WhisperTranscriber(
            settings.whisper_model, settings.whisper_compute_type, settings.whisper_models_dir
        ),
        settings=settings,
        contracts=contracts,
        final_attempt=job["attempts"] >= job["max_attempts"],
        check=check,
        gateway=ModelGateway(settings, contracts),
    )
    log_event(logger, "video processed", source=ref, **{k: v for k, v in result.items() if k != "reason"})
    return None
