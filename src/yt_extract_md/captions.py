from __future__ import annotations

import html
import json
import re
from collections.abc import Callable, Iterable
from typing import Any

from .errors import ConfigError, FetchError, IpBlockedError, MissingCaptionsError, UnavailableError
from .models import Segment, Transcript
from .retrying import retry_transient
from .urls import canonical_url


_TAG_RE = re.compile(r"<[^>]+>")
_BLOCK_WORDS = (
    "too many requests",
    "http error 429",
    "ip address has been blocked",
    "ip address is blocked",
    "request blocked",
    "confirm you're not a bot",
    "confirm you’re not a bot",
    "confirm you are not a bot",
)
_PERMANENT_FAILURE_PATTERNS = (
    re.compile(r"\bvideo unavailable\b", re.IGNORECASE),
    re.compile(r"\bprivate video\b", re.IGNORECASE),
    re.compile(r"\bthis video is private\b", re.IGNORECASE),
    re.compile(r"\bhas been removed\b", re.IGNORECASE),
    re.compile(r"\bvideo (?:is )?not available\b", re.IGNORECASE),
)


def clean_transport_text(text: str) -> str:
    value = html.unescape(text)
    value = re.sub(r"<br\s*/?>", "\n", value, flags=re.IGNORECASE)
    value = _TAG_RE.sub("", value)
    return value.replace("\r\n", "\n").replace("\r", "\n").replace("\n", " ")


def _exception_chain(exc: BaseException) -> Iterable[BaseException]:
    seen: set[int] = set()
    current: BaseException | None = exc
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        yield current
        current = current.__cause__ or current.__context__


def is_ip_block(exc: BaseException) -> bool:
    for current in _exception_chain(exc):
        if type(current).__name__ in {"IpBlocked", "RequestBlocked", "TooManyRequests"}:
            return True
        response = getattr(current, "response", None)
        if getattr(response, "status_code", None) == 429 or getattr(current, "status", None) == 429:
            return True
        if any(word in str(current).lower() for word in _BLOCK_WORDS):
            return True
    return False


def classify_fetch_exception(exc: BaseException, context: str) -> Exception:
    if is_ip_block(exc):
        return IpBlockedError(f"{context} was blocked by YouTube: {exc}")
    for current in _exception_chain(exc):
        name = type(current).__name__
        if name in {"VideoUnavailable", "AgeRestricted", "VideoUnplayable", "PrivateVideo"} or any(
            pattern.search(str(current)) for pattern in _PERMANENT_FAILURE_PATTERNS
        ):
            return UnavailableError(f"Video is unavailable: {exc}")
        if name in {"NoTranscriptFound", "TranscriptsDisabled", "NoSubtitles"}:
            return MissingCaptionsError(f"No configured captions are available: {exc}")
    return FetchError(f"{context} failed: {exc}")


def _entry_value(entry: Any, name: str, default: Any = None) -> Any:
    if isinstance(entry, dict):
        return entry.get(name, default)
    return getattr(entry, name, default)


def transcript_from_yta(entries: Iterable[Any], language: str, generated: bool) -> Transcript:
    segments: list[Segment] = []
    for entry in entries:
        text = clean_transport_text(str(_entry_value(entry, "text", "")))
        if text.strip():
            segments.append(Segment(text, float(_entry_value(entry, "start", 0.0))))
    if not segments:
        raise MissingCaptionsError("The selected caption track was empty")
    return Transcript(tuple(segments), "captions", "generated" if generated else "manual", language)


def _word_spans(text: str) -> list[tuple[str, int, int]]:
    return [(match.group(0), match.start(), match.end()) for match in re.finditer(r"\S+", text)]


def remove_rolling_prefix(previous: str, current: str) -> str:
    previous_words = _word_spans(previous)
    current_words = _word_spans(current)
    if not previous_words or not current_words:
        return current
    previous_values = [value for value, _, _ in previous_words]
    current_values = [value for value, _, _ in current_words]
    maximum = min(len(previous_values), len(current_values))
    longest = next(
        (
            size
            for size in range(maximum, 1, -1)
            if current_values[:size] == previous_values[-size:]
        ),
        0,
    )
    if longest < 2:
        return current
    return current[current_words[longest - 1][2] :].lstrip()


def transcript_from_json3(payload: str | bytes | dict[str, Any], language: str, generated: bool) -> Transcript:
    try:
        data = json.loads(payload) if isinstance(payload, (str, bytes)) else payload
        events = data.get("events", [])
    except (json.JSONDecodeError, AttributeError, TypeError) as exc:
        raise FetchError(f"Could not parse yt-dlp JSON3 captions: {exc}") from exc
    emitted: list[Segment] = []
    previous = ""
    for event in events:
        pieces = event.get("segs") or []
        raw = "".join(str(piece.get("utf8", "")) for piece in pieces)
        text = clean_transport_text(raw)
        if generated:
            text = remove_rolling_prefix(previous, text)
        if text.strip():
            start_ms = float(event.get("tStartMs", 0))
            start_ms += min((float(piece.get("tOffsetMs", 0)) for piece in pieces), default=0.0)
            emitted.append(Segment(text, start_ms / 1000.0))
            previous = clean_transport_text(raw)
    if not emitted:
        raise MissingCaptionsError("The yt-dlp JSON3 caption track was empty")
    return Transcript(tuple(emitted), "captions", "generated" if generated else "manual", language)


class YouTubeTranscriptApiFetcher:
    def __init__(self, retry_call: Callable[[Callable[[], Any]], Any] = retry_transient):
        self.retry_call = retry_call

    def fetch(self, video_id: str, languages: tuple[str, ...]) -> Transcript:
        def operation() -> Transcript:
            try:
                from youtube_transcript_api import YouTubeTranscriptApi
            except ImportError as exc:
                raise ConfigError(
                    "Core dependency youtube-transcript-api is missing; install with: python3 -m pip install ."
                ) from exc
            try:
                transcript_list = YouTubeTranscriptApi().list(video_id)
                try:
                    selected = transcript_list.find_manually_created_transcript(list(languages))
                    generated = False
                except Exception as manual_exc:
                    if type(manual_exc).__name__ not in {"NoTranscriptFound", "NoTranscriptAvailable"}:
                        raise
                    selected = transcript_list.find_generated_transcript(list(languages))
                    generated = True
                entries = selected.fetch()
                language = getattr(selected, "language_code", languages[0])
                return transcript_from_yta(entries, language, generated)
            except (ConfigError, MissingCaptionsError):
                raise
            except Exception as exc:
                raise classify_fetch_exception(exc, "youtube-transcript-api") from exc

        return self.retry_call(operation)


def _select_json3_track(
    tracks: dict[str, list[dict[str, Any]]], languages: tuple[str, ...]
) -> tuple[str, dict[str, Any]] | None:
    for language in languages:
        formats = tracks.get(language) or []
        for item in formats:
            if item.get("ext") == "json3" and item.get("url"):
                return language, item
    return None


class YtDlpCaptionFetcher:
    def __init__(self, retry_call: Callable[[Callable[[], Any]], Any] = retry_transient):
        self.retry_call = retry_call

    def fetch(self, video_id: str, languages: tuple[str, ...]) -> Transcript:
        def operation() -> Transcript:
            try:
                import yt_dlp
            except ImportError as exc:
                raise ConfigError("Core dependency yt-dlp is missing; install with: python3 -m pip install .") from exc
            try:
                options = {"quiet": True, "no_warnings": True, "skip_download": True}
                with yt_dlp.YoutubeDL(options) as ydl:
                    info = ydl.extract_info(canonical_url(video_id), download=False)
                    chosen = _select_json3_track(info.get("subtitles") or {}, languages)
                    generated = False
                    if chosen is None:
                        chosen = _select_json3_track(info.get("automatic_captions") or {}, languages)
                        generated = True
                    if chosen is None:
                        raise MissingCaptionsError("yt-dlp found no configured JSON3 caption track")
                    language, track = chosen
                    with ydl.urlopen(track["url"]) as response:
                        payload = response.read()
                return transcript_from_json3(payload, language, generated)
            except (ConfigError, MissingCaptionsError):
                raise
            except Exception as exc:
                raise classify_fetch_exception(exc, "yt-dlp caption fetch") from exc

        return self.retry_call(operation)


class CaptionAcquirer:
    def __init__(self, primary: Any | None = None, secondary: Any | None = None):
        self.primary = primary or YouTubeTranscriptApiFetcher()
        self.secondary = secondary or YtDlpCaptionFetcher()

    def fetch(self, video_id: str, languages: tuple[str, ...]) -> Transcript:
        errors: list[Exception] = []
        for fetcher in (self.primary, self.secondary):
            try:
                return fetcher.fetch(video_id, languages)
            except (MissingCaptionsError, IpBlockedError, FetchError) as exc:
                errors.append(exc)
            except (ConfigError, UnavailableError) as exc:
                if any(isinstance(error, IpBlockedError) for error in errors):
                    errors.append(exc)
                    continue
                raise
        blocked = [error for error in errors if isinstance(error, IpBlockedError)]
        if blocked:
            raise IpBlockedError(
                "; ".join(str(error) for error in errors),
                both_caption_paths_blocked=len(blocked) == 2,
            )
        fetched = [error for error in errors if isinstance(error, FetchError)]
        if fetched:
            raise FetchError("; ".join(str(error) for error in errors))
        raise MissingCaptionsError("No captions were available from either caption provider")
