from __future__ import annotations

import fcntl
import json
import os
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterator

from .errors import WriteError
from .models import LedgerStatus, Reason
from .output import fsync_directory


@dataclass(frozen=True)
class LedgerEvent:
    video_id: str
    status: str
    reason: str | None
    source: str | None
    processed_at: str
    output_path: str | None
    attempts: int

    @classmethod
    def create(
        cls,
        video_id: str,
        status: LedgerStatus,
        reason: Reason | None,
        source: str | None,
        processed_at: str,
        output_path: str | None,
        attempts: int,
    ) -> "LedgerEvent":
        return cls(video_id, status.value, reason.value if reason else None, source, processed_at, output_path, attempts)


class Ledger:
    def __init__(self, output_dir: Path):
        self.path = output_dir / "ledger.jsonl"
        self.lock_path = output_dir / ".ledger.lock"

    @contextmanager
    def _locked(self) -> Iterator[object]:
        lock = open(self.lock_path, "a+", encoding="utf-8")
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        try:
            yield lock
        finally:
            fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
            lock.close()

    def read_events(self) -> list[LedgerEvent]:
        events: list[LedgerEvent] = []
        try:
            with self._locked():
                if not self.path.exists():
                    return []
                with self.path.open("r", encoding="utf-8") as handle:
                    for line_number, line in enumerate(handle, 1):
                        if not line.strip():
                            continue
                        try:
                            value = json.loads(line)
                            event = LedgerEvent(**value)
                            if event.status not in {item.value for item in LedgerStatus}:
                                raise ValueError(f"unknown status {event.status!r}")
                            if not isinstance(event.attempts, int) or event.attempts < 1:
                                raise ValueError("attempts must be a positive integer")
                            events.append(event)
                        except (json.JSONDecodeError, TypeError, ValueError) as exc:
                            raise WriteError(f"Malformed ledger JSON at {self.path}:{line_number}: {exc}") from exc
        except OSError as exc:
            raise WriteError(f"Could not read ledger {self.path}: {exc}") from exc
        return events

    def latest(self) -> dict[str, LedgerEvent]:
        return {event.video_id: event for event in self.read_events()}

    def append(self, event: LedgerEvent) -> None:
        try:
            with self._locked():
                with self.path.open("a", encoding="utf-8") as handle:
                    handle.write(json.dumps(asdict(event), ensure_ascii=False, separators=(",", ":")) + "\n")
                    handle.flush()
                    os.fsync(handle.fileno())
                fsync_directory(self.path.parent)
        except OSError as exc:
            raise WriteError(f"Could not append ledger {self.path}: {exc}") from exc
