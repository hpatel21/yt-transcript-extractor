from __future__ import annotations

import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .captions import classify_fetch_exception
from .errors import ConfigError, FetchError, IpBlockedError, UnavailableError
from .models import Segment, Transcript
from .retrying import retry_transient
from .urls import canonical_url


class WhisperFetcher:
    def __init__(self, retry_call: Callable[[Callable[[], Any]], Any] = retry_transient):
        self.retry_call = retry_call

    def fetch(self, video_id: str, model_name: str) -> Transcript:
        try:
            from faster_whisper import WhisperModel
        except ImportError as exc:
            raise ConfigError(
                "Whisper fallback was requested but faster-whisper is missing; install with: "
                "python3 -m pip install '.[whisper]'"
            ) from exc
        try:
            import yt_dlp
        except ImportError as exc:
            raise ConfigError("Core dependency yt-dlp is missing; install with: python3 -m pip install .") from exc

        with tempfile.TemporaryDirectory(prefix="yt-extract-md-audio-") as directory:
            temp_dir = Path(directory)
            options = {
                "quiet": True,
                "no_warnings": True,
                "format": "bestaudio/best",
                "outtmpl": str(temp_dir / "audio.%(ext)s"),
                "noplaylist": True,
            }

            def download() -> tuple[dict[str, Any], Path]:
                try:
                    with yt_dlp.YoutubeDL(options) as ydl:
                        info = ydl.extract_info(canonical_url(video_id), download=True)
                    return info, self._audio_path(info, temp_dir)
                except (ConfigError, IpBlockedError, FetchError, UnavailableError):
                    raise
                except Exception as exc:
                    raise classify_fetch_exception(exc, "yt-dlp audio download") from exc

            try:
                _, audio_path = self.retry_call(download)
            except (ConfigError, IpBlockedError, FetchError, UnavailableError):
                raise
            try:
                model = WhisperModel(model_name, device="cpu", compute_type="int8")
                segments, info = model.transcribe(str(audio_path))
                converted = tuple(
                    Segment(str(segment.text), float(segment.start))
                    for segment in segments
                    if str(segment.text).strip()
                )
                if not converted:
                    raise FetchError("Whisper produced an empty transcript")
                language = str(getattr(info, "language", "unknown") or "unknown")
                return Transcript(converted, "whisper", "n/a", language)
            except FetchError:
                raise
            except Exception as exc:
                raise FetchError(f"Whisper transcription failed: {exc}") from exc

    @staticmethod
    def _audio_path(info: dict[str, Any], directory: Path) -> Path:
        for item in info.get("requested_downloads") or []:
            value = item.get("filepath")
            if value and Path(value).is_file():
                return Path(value)
        candidates = [path for path in directory.iterdir() if path.is_file() and path.suffix not in {".part", ".ytdl"}]
        if not candidates:
            raise FetchError("yt-dlp did not produce an audio file for Whisper")
        return candidates[0]
