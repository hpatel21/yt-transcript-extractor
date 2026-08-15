from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path


class Reason(str, Enum):
    INVALID_INPUT = "INVALID_INPUT"
    UNAVAILABLE = "UNAVAILABLE"
    MISSING_CAPTIONS = "MISSING_CAPTIONS"
    IP_BLOCKED = "IP_BLOCKED"
    FETCH_ERROR = "FETCH_ERROR"
    CONFIG_ERROR = "CONFIG_ERROR"
    WRITE_ERROR = "WRITE_ERROR"


class LedgerStatus(str, Enum):
    DONE = "DONE"
    FAILED = "FAILED"
    RETRYABLE = "RETRYABLE"


@dataclass(frozen=True)
class Segment:
    text: str
    start: float


@dataclass(frozen=True)
class Transcript:
    segments: tuple[Segment, ...]
    source: str
    caption_kind: str
    language: str


@dataclass(frozen=True)
class VideoMetadata:
    title: str
    channel: str = "Unknown"
    duration_seconds: int = 0
    published_at: str = ""


@dataclass(frozen=True)
class Artifact:
    video_id: str
    output_path: Path
    transcript: Transcript
    processed_at: str
    recovered_ip_block: bool = False

