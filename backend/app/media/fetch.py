"""Getting a public video's speech (D33, D47): its caption track, or else its audio for local transcription.

No sign-in, cookies, proxies or bot-check workarounds. A refusal (a bot check, a private or removed video, a blocked
network) is recorded and stops the attempt. The media libraries are imported only here, inside the media worker.
"""

from __future__ import annotations

import json
import logging
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from app.media.windows import Cue

logger = logging.getLogger(__name__)


class MediaRefused(Exception):
    """The platform or the network refused. Not worked around; the video stays metadata-only with this reason."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code, self.message = code, message


class MediaUnavailable(Exception):
    """This route does not apply (no caption track, too long, too large); the next route may."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code, self.message = code, message


class MediaError(Exception):
    """A temporary failure (network error, timeout); the job is retried."""


@dataclass
class CaptionTrack:
    language: str
    generated: bool
    cues: list[Cue]


@dataclass
class Transcript:
    language: str | None
    language_probability: float | None
    model_size: str
    cues: list[Cue]


class Captions(Protocol):
    def fetch(self, video_id: str, languages: list[str]) -> CaptionTrack | None: ...


class Audio(Protocol):
    def fetch(self, video_id: str, workdir: Path, *, max_seconds: int, max_bytes: int) -> Path: ...


class Transcriber(Protocol):
    def transcribe(self, wav: Path, language_hint: str | None) -> Transcript: ...


class YouTubeCaptions:
    """youtube-transcript-api: the published caption track, manual before auto-generated, in preferred languages."""

    def fetch(self, video_id: str, languages: list[str]) -> CaptionTrack | None:
        import requests
        import youtube_transcript_api as yta

        api = yta.YouTubeTranscriptApi()
        try:
            tracks = list(api.list(video_id))
        except yta.TranscriptsDisabled:
            return None
        except (yta.RequestBlocked, yta.IpBlocked, yta.PoTokenRequired) as exc:
            raise MediaRefused(
                "captions_blocked", f"YouTube refused the caption request: {type(exc).__name__}"
            ) from exc
        except (yta.VideoUnavailable, yta.VideoUnplayable, yta.AgeRestricted, yta.InvalidVideoId) as exc:
            raise MediaRefused("video_unavailable", f"the video cannot be played: {type(exc).__name__}") from exc
        except requests.exceptions.SSLError as exc:
            raise MediaRefused("network_refused", "the connection to YouTube was refused on this network") from exc
        except (requests.exceptions.RequestException, yta.YouTubeRequestFailed) as exc:
            raise MediaError(f"caption request failed: {type(exc).__name__}") from exc
        if not tracks:
            return None
        wanted = [lang.lower() for lang in languages]

        def rank(track: Any) -> tuple[int, int]:
            code = track.language_code.lower()
            position = wanted.index(code) if code in wanted else len(wanted)
            return (1 if track.is_generated else 0, position)

        track = min(tracks, key=rank)
        try:
            fetched = track.fetch()
        except requests.exceptions.RequestException as exc:
            raise MediaError(f"caption download failed: {type(exc).__name__}") from exc
        cues = [
            Cue(round(s.start * 1000), round((s.start + s.duration) * 1000), s.text)
            for s in fetched.snippets
            if s.text and s.text.strip()
        ]
        return CaptionTrack(track.language_code, bool(track.is_generated), cues)


class YtDlpAudio:
    """yt-dlp best audio within the size and length caps, then ffmpeg to 16 kHz mono WAV. Nothing is kept."""

    def fetch(self, video_id: str, workdir: Path, *, max_seconds: int, max_bytes: int) -> Path:
        import yt_dlp

        def within_limits(info: dict[str, Any], *, incomplete: bool = False) -> str | None:
            duration = info.get("duration")
            if duration and duration > max_seconds:
                return f"longer than {max_seconds} s"
            return None

        options = {
            "format": "bestaudio/best",
            "outtmpl": str(workdir / "source.%(ext)s"),
            "noplaylist": True,
            "quiet": True,
            "no_warnings": True,
            "max_filesize": max_bytes,
            "match_filter": within_limits,
            "cookiefile": None,
            "proxy": "",
            "retries": 2,
            "socket_timeout": 30,
        }
        try:
            with yt_dlp.YoutubeDL(options) as ydl:
                ydl.extract_info(f"https://www.youtube.com/watch?v={video_id}", download=True)
        except yt_dlp.utils.DownloadError as exc:
            text = str(exc).lower()
            if "confirm you" in text or "sign in" in text or "not a bot" in text:
                raise MediaRefused(
                    "bot_check", "YouTube asked to sign in or confirm a human; not worked around"
                ) from exc
            if "private" in text or "unavailable" in text or "removed" in text:
                raise MediaRefused("video_unavailable", "the video cannot be downloaded: unavailable") from exc
            if "ssl" in text or "connection reset" in text or "eof occurred" in text:
                raise MediaRefused("network_refused", "the connection to YouTube was refused on this network") from exc
            raise MediaError(f"audio download failed: {str(exc)[:200]}") from exc
        downloaded = [p for p in workdir.iterdir() if p.name.startswith("source.")]
        if not downloaded:
            raise MediaUnavailable("not_downloaded", "longer than the limit or larger than the size cap")
        return to_wav(downloaded[0], workdir / "audio.wav", max_seconds=max_seconds)


def ffmpeg_binary(name: str) -> str:
    found = shutil.which(name)
    if found is None:
        raise MediaError(f"{name} is not installed")
    return found


def to_wav(source: Path, target: Path, *, max_seconds: int, timeout: int = 600) -> Path:
    """16 kHz mono PCM WAV, cut at `max_seconds`; the result is checked with ffprobe."""
    command = [
        ffmpeg_binary("ffmpeg"),
        "-nostdin",
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-i",
        str(source),
        "-vn",
        "-t",
        str(max_seconds),
        "-ac",
        "1",
        "-ar",
        "16000",
        "-f",
        "wav",
        str(target),
    ]
    try:
        subprocess.run(command, check=True, capture_output=True, timeout=timeout)  # noqa: S603
    except subprocess.CalledProcessError as exc:
        raise MediaUnavailable("not_audio", f"ffmpeg could not read the file: {exc.stderr[-200:]!r}") from exc
    except subprocess.TimeoutExpired as exc:
        raise MediaError("ffmpeg timed out") from exc
    probe = subprocess.run(  # noqa: S603
        [
            ffmpeg_binary("ffprobe"),
            "-v",
            "error",
            "-show_entries",
            "stream=codec_type,sample_rate,channels",
            "-show_entries",
            "format=duration",
            "-of",
            "json",
            str(target),
        ],
        check=True,
        capture_output=True,
        timeout=60,
    )
    info = json.loads(probe.stdout)
    stream = (info.get("streams") or [{}])[0]
    if stream.get("codec_type") != "audio" or stream.get("sample_rate") != "16000" or stream.get("channels") != 1:
        raise MediaUnavailable("not_audio", "the converted file is not 16 kHz mono audio")
    if float((info.get("format") or {}).get("duration") or 0) > max_seconds + 1:
        raise MediaUnavailable("too_long", f"longer than {max_seconds} s after conversion")
    return target


def read_wav(path: Path) -> Any:
    """Samples of our own 16 kHz mono 16-bit WAV as float32. faster-whisper's decoder is bypassed: it calls PyAV
    with an argument that av 19 removed, and ffmpeg has already produced and checked this file."""
    import wave

    import numpy as np

    with wave.open(str(path), "rb") as audio:
        if audio.getframerate() != 16000 or audio.getnchannels() != 1 or audio.getsampwidth() != 2:
            raise MediaUnavailable("not_audio", "expected 16 kHz mono 16-bit audio")
        frames = audio.readframes(audio.getnframes())
    return np.frombuffer(frames, dtype=np.int16).astype(np.float32) / 32768.0


class WhisperTranscriber:
    """faster-whisper on the CPU, loaded once per worker process."""

    _models: dict[tuple[str, str], Any] = {}  # noqa: RUF012  (process-wide cache by design)

    def __init__(self, model_size: str, compute_type: str, models_dir: Path) -> None:
        self.model_size, self.compute_type, self.models_dir = model_size, compute_type, models_dir

    def _model(self) -> Any:
        key = (self.model_size, self.compute_type)
        if key not in self._models:
            from faster_whisper import WhisperModel

            self._models[key] = WhisperModel(
                self.model_size, device="cpu", compute_type=self.compute_type, download_root=str(self.models_dir)
            )
        return self._models[key]

    def transcribe(self, wav: Path, language_hint: str | None) -> Transcript:
        hint = (language_hint or "").split("-")[0].lower() or None
        segments, info = self._model().transcribe(
            read_wav(wav),
            language=hint if hint in ("hi", "en") else None,
            vad_filter=True,
            beam_size=5,
            condition_on_previous_text=False,  # fewer repeated or invented lines on music and silence
        )
        cues = [
            Cue(round(s.start * 1000), round(s.end * 1000), s.text, s.avg_logprob, s.no_speech_prob) for s in segments
        ]
        return Transcript(info.language, info.language_probability, self.model_size, cues)
