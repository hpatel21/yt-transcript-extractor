from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import urlopen

from .captions import classify_fetch_exception
from .errors import ConfigError, FetchError, IpBlockedError, UnavailableError
from .models import VideoMetadata
from .retrying import retry_transient
from .urls import canonical_url


def default_metadata(video_id: str) -> VideoMetadata:
    return VideoMetadata(title=f"Video {video_id}")


def _date(value: Any) -> str:
    text = str(value or "")
    if len(text) == 8 and text.isdigit():
        return f"{text[:4]}-{text[4:6]}-{text[6:]}"
    return text


class MetadataFetcher:
    def __init__(self, retry_call: Callable[[Callable[[], Any]], Any] = retry_transient):
        self.retry_call = retry_call

    def fetch(self, video_id: str) -> VideoMetadata:
        try:
            import yt_dlp
        except ImportError:
            return self._oembed(video_id)

        def fetch_ytdlp() -> VideoMetadata:
            try:
                options = {"quiet": True, "no_warnings": True, "skip_download": True}
                with yt_dlp.YoutubeDL(options) as ydl:
                    info = ydl.extract_info(canonical_url(video_id), download=False)
                return VideoMetadata(
                    title=str(info.get("title") or f"Video {video_id}"),
                    channel=str(info.get("channel") or info.get("uploader") or "Unknown"),
                    duration_seconds=int(info.get("duration") or 0),
                    published_at=_date(info.get("upload_date") or info.get("release_date")),
                )
            except (KeyError, TypeError, ValueError) as exc:
                raise FetchError(f"Invalid yt-dlp metadata response: {exc}") from exc
            except MemoryError:
                raise
            except Exception as exc:
                raise classify_fetch_exception(exc, "yt-dlp metadata fetch") from exc

        try:
            return self.retry_call(fetch_ytdlp)
        except (ConfigError, FetchError, IpBlockedError, UnavailableError):
            return self._oembed(video_id)

    def _oembed(self, video_id: str) -> VideoMetadata:
        endpoint = "https://www.youtube.com/oembed?" + urlencode(
            {"url": canonical_url(video_id), "format": "json"}
        )
        try:
            with urlopen(endpoint, timeout=15) as response:
                value = json.loads(response.read())
            if not isinstance(value, Mapping):
                return default_metadata(video_id)
            return VideoMetadata(
                title=str(value.get("title") or f"Video {video_id}"),
                channel=str(value.get("author_name") or "Unknown"),
            )
        except MemoryError:
            raise
        except (HTTPError, URLError, TimeoutError, OSError, json.JSONDecodeError, TypeError, ValueError):
            return default_metadata(video_id)
