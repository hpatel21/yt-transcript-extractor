from __future__ import annotations

import random
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, TextIO

from .captions import CaptionAcquirer
from .errors import (
    ConfigError,
    ExtractorError,
    FetchError,
    InvalidInputError,
    IpBlockedError,
    MissingCaptionsError,
    UnavailableError,
    WriteError,
)
from .ledger import Ledger, LedgerEvent
from .metadata import MetadataFetcher, default_metadata
from .models import Artifact, LedgerStatus, Reason
from .output import utc_now, write_transcript
from .queue import QueueFile
from .urls import normalize_video_id
from .whisper import WhisperFetcher


EXIT_OK = 0
EXIT_FAILED = 1
EXIT_USAGE = 2
EXIT_IP_BLOCKED = 3
EXIT_CONFIG = 4
EXIT_WRITE = 5
MAX_TRANSIENT_ATTEMPTS = 3


@dataclass(frozen=True)
class ExtractOptions:
    output_format: str = "md"
    timestamps: bool = True
    languages: tuple[str, ...] = ("en", "en-US", "en-GB")
    whisper_fallback: bool = False
    whisper_model: str = "base"


class ExtractService:
    def __init__(
        self,
        caption_acquirer: Any | None = None,
        whisper_fetcher: Any | None = None,
        metadata_fetcher: Any | None = None,
    ):
        self.caption_acquirer = caption_acquirer or CaptionAcquirer()
        self.whisper_fetcher = whisper_fetcher or WhisperFetcher()
        self.metadata_fetcher = metadata_fetcher or MetadataFetcher()

    def extract(self, value: str, output_dir: Path, options: ExtractOptions) -> Artifact:
        video_id = normalize_video_id(value)
        recovered_ip = False
        try:
            transcript = self.caption_acquirer.fetch(video_id, options.languages)
        except (MissingCaptionsError, IpBlockedError) as caption_error:
            if not options.whisper_fallback:
                raise
            try:
                transcript = self.whisper_fetcher.fetch(video_id, options.whisper_model)
            except (ConfigError, FetchError, IpBlockedError, MissingCaptionsError, UnavailableError) as whisper_error:
                if isinstance(caption_error, IpBlockedError):
                    stopping_error = type(whisper_error)(str(whisper_error), stop_batch=True)
                    raise stopping_error from whisper_error
                raise
            recovered_ip = isinstance(caption_error, IpBlockedError)
        try:
            metadata = self.metadata_fetcher.fetch(video_id)
        except (MemoryError, WriteError):
            raise
        except Exception:
            metadata = default_metadata(video_id)
        output_path, processed_at = write_transcript(
            output_dir,
            video_id,
            metadata,
            transcript,
            options.output_format,
            options.timestamps,
        )
        return Artifact(video_id, output_path, transcript, processed_at, recovered_ip)


class Application:
    def __init__(
        self,
        service: ExtractService | None = None,
        sleeper: Callable[[float], None] = time.sleep,
        random_uniform: Callable[[float, float], float] = random.uniform,
        stdout: TextIO = sys.stdout,
        stderr: TextIO = sys.stderr,
    ):
        self.service = service or ExtractService()
        self.sleeper = sleeper
        self.random_uniform = random_uniform
        self.stdout = stdout
        self.stderr = stderr

    @staticmethod
    def _attempt(latest: dict[str, LedgerEvent], video_id: str) -> int:
        previous = latest.get(video_id)
        return (previous.attempts if previous else 0) + 1

    def _append_failure(
        self,
        ledger: Ledger,
        video_id: str,
        error: ExtractorError,
        attempts: int,
    ) -> LedgerStatus:
        terminal = not error.retryable or attempts >= MAX_TRANSIENT_ATTEMPTS
        status = LedgerStatus.FAILED if terminal else LedgerStatus.RETRYABLE
        ledger.append(LedgerEvent.create(video_id, status, error.reason, None, utc_now(), None, attempts))
        return status

    def run_extract(self, value: str, output_dir: Path, options: ExtractOptions) -> int:
        ledger = Ledger(output_dir)
        try:
            video_id = normalize_video_id(value)
            latest = ledger.latest()
            previous = latest.get(video_id)
            if previous and previous.status in {LedgerStatus.DONE.value, LedgerStatus.FAILED.value}:
                print(f"Skipping terminal video {video_id}: {previous.status}", file=self.stdout)
                return EXIT_OK if previous.status == LedgerStatus.DONE.value else EXIT_FAILED
            attempts = self._attempt(latest, video_id)
            artifact = self.service.extract(video_id, output_dir, options)
            ledger.append(
                LedgerEvent.create(
                    video_id,
                    LedgerStatus.DONE,
                    None,
                    artifact.transcript.source,
                    artifact.processed_at,
                    str(artifact.output_path),
                    attempts,
                )
            )
            print(str(artifact.output_path), file=self.stdout)
            return EXIT_IP_BLOCKED if artifact.recovered_ip_block else EXIT_OK
        except ConfigError as exc:
            print(f"CONFIG_ERROR: {exc}", file=self.stderr)
            return EXIT_IP_BLOCKED if exc.stop_batch else EXIT_CONFIG
        except WriteError as exc:
            print(f"WRITE_ERROR: {exc}", file=self.stderr)
            return EXIT_WRITE
        except InvalidInputError as exc:
            print(f"INVALID_INPUT: {exc}", file=self.stderr)
            return EXIT_USAGE
        except ExtractorError as exc:
            try:
                status = self._append_failure(ledger, video_id, exc, attempts)
            except WriteError as ledger_error:
                print(f"WRITE_ERROR: {ledger_error}", file=self.stderr)
                return EXIT_WRITE
            print(f"{exc.reason.value}: {exc}", file=self.stderr)
            if isinstance(exc, IpBlockedError):
                return EXIT_IP_BLOCKED
            return EXIT_FAILED if status == LedgerStatus.FAILED else EXIT_FAILED

    def run_batch(self, queue_path: Path, output_dir: Path, options: ExtractOptions) -> int:
        queue = QueueFile(queue_path)
        ledger = Ledger(output_dir)
        attempted_this_run: set[str] = set()
        reported_invalid: set[str] = set()
        any_failure = False
        attempts_made = 0
        while True:
            try:
                latest = ledger.latest()
                lines = queue.snapshot()
            except InvalidInputError as exc:
                print(f"INVALID_INPUT: {exc}", file=self.stderr)
                return EXIT_USAGE
            except WriteError as exc:
                print(f"WRITE_ERROR: {exc}", file=self.stderr)
                return EXIT_WRITE

            candidate: tuple[str, str] | None = None
            removed_terminal = False
            for line in lines:
                value = line.strip()
                if not value or value.startswith("#"):
                    continue
                try:
                    video_id = normalize_video_id(value)
                except InvalidInputError as exc:
                    if value not in reported_invalid:
                        print(f"INVALID_INPUT: {exc}; line retained", file=self.stderr)
                        reported_invalid.add(value)
                        any_failure = True
                    continue
                previous = latest.get(video_id)
                if previous and previous.status in {LedgerStatus.DONE.value, LedgerStatus.FAILED.value}:
                    queue.remove_video(video_id)
                    removed_terminal = True
                    break
                if video_id not in attempted_this_run:
                    candidate = value, video_id
                    break
            if removed_terminal:
                continue
            if candidate is None:
                return EXIT_FAILED if any_failure else EXIT_OK
            value, video_id = candidate
            if attempts_made:
                self.sleeper(self.random_uniform(2.0, 4.5))
            attempts_made += 1
            attempted_this_run.add(video_id)
            attempt = self._attempt(latest, video_id)
            try:
                artifact = self.service.extract(value, output_dir, options)
                ledger.append(
                    LedgerEvent.create(
                        video_id,
                        LedgerStatus.DONE,
                        None,
                        artifact.transcript.source,
                        artifact.processed_at,
                        str(artifact.output_path),
                        attempt,
                    )
                )
                queue.remove_video(video_id)
                print(str(artifact.output_path), file=self.stdout)
                if artifact.recovered_ip_block:
                    print("IP_BLOCKED: Whisper recovered the current item; stopping batch", file=self.stderr)
                    return EXIT_IP_BLOCKED
            except ConfigError as exc:
                print(f"CONFIG_ERROR: {exc}; line retained", file=self.stderr)
                return EXIT_IP_BLOCKED if exc.stop_batch else EXIT_CONFIG
            except WriteError as exc:
                print(f"WRITE_ERROR: {exc}; line retained", file=self.stderr)
                return EXIT_WRITE
            except InvalidInputError as exc:
                print(f"INVALID_INPUT: {exc}; line retained", file=self.stderr)
                any_failure = True
            except ExtractorError as exc:
                try:
                    status = self._append_failure(ledger, video_id, exc, attempt)
                except WriteError as ledger_error:
                    print(f"WRITE_ERROR: {ledger_error}; line retained", file=self.stderr)
                    return EXIT_WRITE
                terminal = status == LedgerStatus.FAILED
                if terminal:
                    try:
                        queue.remove_video(video_id)
                    except WriteError as queue_error:
                        print(f"WRITE_ERROR: {queue_error}; line retained", file=self.stderr)
                        return EXIT_WRITE
                print(
                    f"{exc.reason.value}: {exc}; line {'removed' if terminal else 'retained'}",
                    file=self.stderr,
                )
                any_failure = True
                if isinstance(exc, IpBlockedError) or exc.stop_batch:
                    return EXIT_IP_BLOCKED
