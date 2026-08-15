from __future__ import annotations

import errno
import json
import os
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from . import __version__
from .errors import WriteError
from .models import Transcript, VideoMetadata
from .urls import canonical_url


_UNSUPPORTED_DIRECTORY_SYNC_ERRNOS = {
    errno.EINVAL,
    getattr(errno, "ENOTSUP", errno.EINVAL),
    getattr(errno, "EOPNOTSUPP", errno.EINVAL),
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def validate_output_dir(value: str | Path) -> Path:
    path = Path(value)
    if not path.exists():
        raise WriteError(f"Output directory does not exist: {path}")
    if not path.is_dir():
        raise WriteError(f"Output path is not a directory: {path}")
    if not os.access(path, os.W_OK):
        raise WriteError(f"Output directory is not writable: {path}")
    return path


def sanitize_title(title: str, limit: int = 80) -> str:
    ascii_title = title.encode("ascii", "ignore").decode("ascii")
    ascii_title = re.sub(r"[<>:\"/\\|?*\x00-\x1f\x7f]", " ", ascii_title)
    ascii_title = re.sub(r"[^A-Za-z0-9._ -]", " ", ascii_title)
    ascii_title = re.sub(r"[\s_]+", "_", ascii_title)
    ascii_title = ascii_title.strip("._- ")[:limit].rstrip("._- ")
    return ascii_title or "video"


def output_filename(title: str, video_id: str, output_format: str) -> str:
    return f"{sanitize_title(title)}_{video_id}.{output_format}"


def _timestamp(seconds: float) -> str:
    whole = max(0, int(seconds))
    hours, remainder = divmod(whole, 3600)
    minutes, secs = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"


def _body(transcript: Transcript, timestamps: bool) -> str:
    lines = []
    for segment in transcript.segments:
        lines.append(f"[{_timestamp(segment.start)}] {segment.text}" if timestamps else segment.text)
    return "\n".join(lines) + ("\n" if lines else "")


def render_markdown(
    video_id: str,
    metadata: VideoMetadata,
    transcript: Transcript,
    processed_at: str,
    timestamps: bool = True,
) -> str:
    fields: list[tuple[str, object]] = [
        ("video_id", video_id),
        ("video_url", canonical_url(video_id)),
        ("title", metadata.title),
        ("channel", metadata.channel),
        ("duration_seconds", metadata.duration_seconds),
        ("published_at", metadata.published_at),
        ("transcript_source", transcript.source),
        ("caption_kind", transcript.caption_kind),
        ("language", transcript.language),
        ("processed_at", processed_at),
        ("extractor_version", __version__),
    ]
    header = ["---"]
    for key, value in fields:
        rendered = str(value) if isinstance(value, int) else json.dumps(value, ensure_ascii=False)
        header.append(f"{key}: {rendered}")
    header.extend(["---", ""])
    return "\n".join(header) + _body(transcript, timestamps)


def render_text(
    video_id: str,
    metadata: VideoMetadata,
    transcript: Transcript,
    processed_at: str,
    timestamps: bool = True,
) -> str:
    fields = [
        ("Video ID", video_id),
        ("Video URL", canonical_url(video_id)),
        ("Title", metadata.title),
        ("Channel", metadata.channel),
        ("Duration seconds", str(metadata.duration_seconds)),
        ("Published at", metadata.published_at),
        ("Transcript source", transcript.source),
        ("Caption kind", transcript.caption_kind),
        ("Language", transcript.language),
        ("Processed at", processed_at),
        ("Extractor version", __version__),
    ]
    return "\n".join(f"{key}: {value}" for key, value in fields) + "\n\n" + _body(transcript, timestamps)


def fsync_directory(path: Path) -> None:
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    try:
        descriptor = os.open(os.fspath(path), flags)
    except OSError as exc:
        if exc.errno in _UNSUPPORTED_DIRECTORY_SYNC_ERRNOS:
            return
        raise WriteError(f"Could not open directory for durability sync {path}: {exc}") from exc

    failure: tuple[str, OSError] | None = None
    try:
        os.fsync(descriptor)
    except OSError as exc:
        if exc.errno not in _UNSUPPORTED_DIRECTORY_SYNC_ERRNOS:
            failure = (f"Could not durability-sync directory {path}: {exc}", exc)
    try:
        os.close(descriptor)
    except OSError as exc:
        if failure is None:
            failure = (f"Could not close durability-sync directory {path}: {exc}", exc)
    if failure is not None:
        raise WriteError(failure[0]) from failure[1]


def atomic_write(path: Path, content: str) -> None:
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=path.parent, prefix=f".{path.name}.", suffix=".tmp", delete=False
        ) as handle:
            temporary = Path(handle.name)
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        fsync_directory(path.parent)
        temporary = None
    except OSError as exc:
        raise WriteError(f"Could not atomically write {path}: {exc}") from exc
    finally:
        if temporary is not None:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass


def write_transcript(
    output_dir: Path,
    video_id: str,
    metadata: VideoMetadata,
    transcript: Transcript,
    output_format: str,
    timestamps: bool,
    processed_at: str | None = None,
) -> tuple[Path, str]:
    processed = processed_at or utc_now()
    destination = output_dir / output_filename(metadata.title, video_id, output_format)
    if output_format == "md":
        content = render_markdown(video_id, metadata, transcript, processed, timestamps)
    elif output_format == "txt":
        content = render_text(video_id, metadata, transcript, processed, timestamps)
    else:
        raise WriteError(f"Unsupported output format: {output_format}")
    atomic_write(destination, content)
    return destination, processed
