from __future__ import annotations

import re
from urllib.parse import parse_qs, urlparse

from .errors import InvalidInputError


VIDEO_ID_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")
YOUTUBE_HOSTS = {"youtube.com", "www.youtube.com", "m.youtube.com", "music.youtube.com"}


def normalize_video_id(value: str) -> str:
    candidate = value.strip()
    if VIDEO_ID_RE.fullmatch(candidate):
        return candidate
    try:
        parsed = urlparse(candidate)
    except ValueError as exc:
        raise InvalidInputError(f"Invalid YouTube URL: {value!r}") from exc
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise InvalidInputError(f"Expected an 11-character YouTube ID or video URL: {value!r}")
    host = parsed.hostname.lower().rstrip(".")
    video_id: str | None = None
    if host == "youtu.be":
        parts = [part for part in parsed.path.split("/") if part]
        video_id = parts[0] if len(parts) == 1 else None
    elif host in YOUTUBE_HOSTS:
        parts = [part for part in parsed.path.split("/") if part]
        if parsed.path.rstrip("/") == "/watch":
            values = parse_qs(parsed.query).get("v", [])
            video_id = values[0] if len(values) == 1 else None
        elif len(parts) == 2 and parts[0] in {"shorts", "embed", "v"}:
            video_id = parts[1]
    else:
        raise InvalidInputError(f"Unsupported host {host!r}; expected youtube.com or youtu.be")
    if video_id is None or not VIDEO_ID_RE.fullmatch(video_id):
        raise InvalidInputError(f"Malformed YouTube video ID in {value!r}")
    return video_id


def canonical_url(video_id: str) -> str:
    if not VIDEO_ID_RE.fullmatch(video_id):
        raise InvalidInputError(f"Malformed YouTube video ID: {video_id!r}")
    return f"https://www.youtube.com/watch?v={video_id}"

