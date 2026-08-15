from __future__ import annotations

import fcntl
import os
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from .errors import InvalidInputError, WriteError
from .output import fsync_directory
from .urls import canonical_url, normalize_video_id


class QueueFile:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.lock_path = self.path.with_name(self.path.name + ".lock")

    @contextmanager
    def _lock(self) -> Iterator[None]:
        try:
            with self.lock_path.open("a+", encoding="utf-8") as handle:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
                try:
                    yield
                finally:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        except OSError as exc:
            raise WriteError(f"Could not lock queue {self.path}: {exc}") from exc

    def _read_lines_unlocked(self) -> list[str]:
        try:
            return self.path.read_text(encoding="utf-8").splitlines(keepends=True)
        except FileNotFoundError as exc:
            raise InvalidInputError(f"Queue file does not exist: {self.path}") from exc
        except OSError as exc:
            raise WriteError(f"Could not read queue {self.path}: {exc}") from exc

    def snapshot(self) -> list[str]:
        with self._lock():
            return self._read_lines_unlocked()

    def _replace_unlocked(self, lines: list[str]) -> None:
        temporary: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", dir=self.path.parent, prefix=f".{self.path.name}.", suffix=".tmp", delete=False
            ) as handle:
                temporary = Path(handle.name)
                handle.writelines(lines)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.path)
            fsync_directory(self.path.parent)
            temporary = None
        except OSError as exc:
            raise WriteError(f"Could not atomically update queue {self.path}: {exc}") from exc
        finally:
            if temporary is not None:
                try:
                    temporary.unlink(missing_ok=True)
                except OSError:
                    pass

    def remove_video(self, video_id: str) -> int:
        with self._lock():
            lines = self._read_lines_unlocked()
            kept: list[str] = []
            removed = 0
            for line in lines:
                value = line.strip()
                if not value or value.startswith("#"):
                    kept.append(line)
                    continue
                try:
                    matches = normalize_video_id(value) == video_id
                except InvalidInputError:
                    matches = False
                if matches:
                    removed += 1
                else:
                    kept.append(line)
            if removed:
                self._replace_unlocked(kept)
            return removed

    def enqueue(self, values: list[str]) -> list[str]:
        requested = [normalize_video_id(value) for value in values]
        added: list[str] = []
        with self._lock():
            lines = self._read_lines_unlocked() if self.path.exists() else []
            existing: set[str] = set()
            for line in lines:
                value = line.strip()
                if not value or value.startswith("#"):
                    continue
                try:
                    existing.add(normalize_video_id(value))
                except InvalidInputError:
                    continue
            for video_id in requested:
                if video_id not in existing:
                    added.append(video_id)
                    existing.add(video_id)
            if added:
                if lines and not lines[-1].endswith(("\n", "\r")):
                    lines[-1] += "\n"
                lines.extend(canonical_url(video_id) + "\n" for video_id in added)
                self._replace_unlocked(lines)
            elif not self.path.exists():
                self._replace_unlocked([])
        return added
