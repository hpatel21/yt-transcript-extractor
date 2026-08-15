import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from yt_extract_md.errors import (
    ConfigError,
    FetchError,
    IpBlockedError,
    MissingCaptionsError,
    UnavailableError,
    WriteError,
)
from yt_extract_md.ledger import Ledger
from yt_extract_md.models import Artifact, Segment, Transcript, VideoMetadata
from yt_extract_md.service import (
    Application,
    EXIT_FAILED,
    EXIT_IP_BLOCKED,
    EXIT_OK,
    ExtractOptions,
    ExtractService,
)


VIDEO_ID = "0l3vUprzNzg"
OTHER_ID = "ZAGbis1hfXw"
TRANSCRIPT = Transcript((Segment("hello", 0),), "captions", "manual", "en")
WHISPER = Transcript((Segment(" local text", 0),), "whisper", "n/a", "en")


class Metadata:
    def fetch(self, video_id):
        return VideoMetadata("Title")


class RaisingCaptions:
    def __init__(self, error):
        self.error = error

    def fetch(self, video_id, languages):
        raise self.error


class FixedWhisper:
    def __init__(self, value):
        self.value = value

    def fetch(self, video_id, model_name):
        if isinstance(self.value, Exception):
            raise self.value
        return self.value


class FixedService:
    def __init__(self, result):
        self.result = result
        self.calls = []

    def extract(self, value, output_dir, options):
        self.calls.append(value)
        if isinstance(self.result, Exception):
            raise self.result
        video_id = value if len(value) == 11 else VIDEO_ID
        return Artifact(video_id, output_dir / f"{video_id}.md", TRANSCRIPT, "2026-08-15T00:00:00Z")


class ServiceTests(unittest.TestCase):
    def test_missing_captions_use_whisper_without_stopping_batch(self):
        service = ExtractService(RaisingCaptions(MissingCaptionsError("none")), FixedWhisper(WHISPER), Metadata())
        with tempfile.TemporaryDirectory() as directory:
            artifact = service.extract(VIDEO_ID, Path(directory), ExtractOptions(whisper_fallback=True))
            self.assertEqual(artifact.transcript.source, "whisper")
            self.assertFalse(artifact.recovered_ip_block)
            self.assertTrue(artifact.output_path.exists())

    def test_ip_block_whisper_recovery_writes_done_removes_current_then_stops(self):
        captions_error = IpBlockedError("one blocked", both_caption_paths_blocked=False)
        service = ExtractService(RaisingCaptions(captions_error), FixedWhisper(WHISPER), Metadata())
        stderr = io.StringIO()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            queue = root / "queue.txt"
            queue.write_text(f"{VIDEO_ID}\n{OTHER_ID}\n", encoding="utf-8")
            app = Application(service, sleeper=lambda value: None, stderr=stderr, stdout=io.StringIO())
            code = app.run_batch(queue, root, ExtractOptions(whisper_fallback=True))
            self.assertEqual(code, EXIT_IP_BLOCKED)
            self.assertEqual(queue.read_text(), f"{OTHER_ID}\n")
            latest = Ledger(root).latest()[VIDEO_ID]
            self.assertEqual((latest.status, latest.source), ("DONE", "whisper"))
            self.assertTrue(Path(latest.output_path).exists())

    def test_single_extract_whisper_recovery_after_ip_block_persists_done_and_returns_ip_exit(self):
        service = ExtractService(
            RaisingCaptions(IpBlockedError("one caption path blocked")), FixedWhisper(WHISPER), Metadata()
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            code = Application(service, stderr=io.StringIO(), stdout=io.StringIO()).run_extract(
                VIDEO_ID, root, ExtractOptions(whisper_fallback=True)
            )
            self.assertEqual(code, EXIT_IP_BLOCKED)
            latest = Ledger(root).latest()[VIDEO_ID]
            self.assertEqual((latest.status, latest.source), ("DONE", "whisper"))

    def test_audio_fetch_failure_after_ip_block_is_retained_and_stops(self):
        captions_error = IpBlockedError("both blocked", both_caption_paths_blocked=True)
        service = ExtractService(RaisingCaptions(captions_error), FixedWhisper(FetchError("audio failed")), Metadata())
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            queue = root / "queue.txt"
            queue.write_text(f"{VIDEO_ID}\n{OTHER_ID}\n", encoding="utf-8")
            code = Application(service, stderr=io.StringIO(), stdout=io.StringIO()).run_batch(
                queue, root, ExtractOptions(whisper_fallback=True)
            )
            self.assertEqual(code, EXIT_IP_BLOCKED)
            self.assertEqual(queue.read_text(), f"{VIDEO_ID}\n{OTHER_ID}\n")
            latest = Ledger(root).latest()[VIDEO_ID]
            self.assertEqual((latest.status, latest.reason), ("RETRYABLE", "FETCH_ERROR"))

    def test_audio_ip_block_after_caption_ip_block_stays_ip_blocked_and_stops(self):
        service = ExtractService(
            RaisingCaptions(IpBlockedError("caption blocked")),
            FixedWhisper(IpBlockedError("audio blocked")),
            Metadata(),
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            queue = root / "queue.txt"
            queue.write_text(f"{VIDEO_ID}\n{OTHER_ID}\n", encoding="utf-8")
            code = Application(service, stderr=io.StringIO(), stdout=io.StringIO()).run_batch(
                queue, root, ExtractOptions(whisper_fallback=True)
            )
            self.assertEqual(code, EXIT_IP_BLOCKED)
            self.assertEqual(queue.read_text(), f"{VIDEO_ID}\n{OTHER_ID}\n")
            latest = Ledger(root).latest()[VIDEO_ID]
            self.assertEqual((latest.status, latest.reason), ("RETRYABLE", "IP_BLOCKED"))

    def test_audio_unavailable_after_caption_ip_block_is_terminal_but_stops(self):
        service = ExtractService(
            RaisingCaptions(IpBlockedError("caption blocked")),
            FixedWhisper(UnavailableError("removed")),
            Metadata(),
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            queue = root / "queue.txt"
            queue.write_text(f"{VIDEO_ID}\n{OTHER_ID}\n", encoding="utf-8")
            code = Application(service, stderr=io.StringIO(), stdout=io.StringIO()).run_batch(
                queue, root, ExtractOptions(whisper_fallback=True)
            )
            self.assertEqual(code, EXIT_IP_BLOCKED)
            self.assertEqual(queue.read_text(), f"{OTHER_ID}\n")
            latest = Ledger(root).latest()[VIDEO_ID]
            self.assertEqual((latest.status, latest.reason), ("FAILED", "UNAVAILABLE"))

    def test_whisper_config_failure_after_caption_ip_block_retains_item_but_stops(self):
        service = ExtractService(
            RaisingCaptions(IpBlockedError("caption blocked")),
            FixedWhisper(ConfigError("whisper missing")),
            Metadata(),
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            queue = root / "queue.txt"
            queue.write_text(f"{VIDEO_ID}\n{OTHER_ID}\n", encoding="utf-8")
            code = Application(service, stderr=io.StringIO(), stdout=io.StringIO()).run_batch(
                queue, root, ExtractOptions(whisper_fallback=True)
            )
            self.assertEqual(code, EXIT_IP_BLOCKED)
            self.assertEqual(queue.read_text(), f"{VIDEO_ID}\n{OTHER_ID}\n")
            self.assertNotIn(VIDEO_ID, Ledger(root).latest())

    def test_unexpected_metadata_failure_uses_defaults_and_persists_transcript(self):
        class BrokenMetadata:
            def fetch(self, video_id):
                raise AttributeError("unexpected parsed shape")

        service = ExtractService(
            caption_acquirer=type("Captions", (), {"fetch": lambda self, video_id, languages: TRANSCRIPT})(),
            metadata_fetcher=BrokenMetadata(),
        )
        with tempfile.TemporaryDirectory() as directory:
            artifact = service.extract(VIDEO_ID, Path(directory), ExtractOptions())
            self.assertTrue(artifact.output_path.exists())
            self.assertIn(f"Video_{VIDEO_ID}", artifact.output_path.name)
            self.assertIn("hello", artifact.output_path.read_text(encoding="utf-8"))

    def test_metadata_memory_error_is_not_contained(self):
        class BrokenMetadata:
            def fetch(self, video_id):
                raise MemoryError("out of memory")

        service = ExtractService(
            caption_acquirer=type("Captions", (), {"fetch": lambda self, video_id, languages: TRANSCRIPT})(),
            metadata_fetcher=BrokenMetadata(),
        )
        with tempfile.TemporaryDirectory() as directory, self.assertRaises(MemoryError):
            service.extract(VIDEO_ID, Path(directory), ExtractOptions())

    def test_metadata_write_error_is_not_contained(self):
        class BrokenMetadata:
            def fetch(self, video_id):
                raise WriteError("storage failure")

        service = ExtractService(
            caption_acquirer=type("Captions", (), {"fetch": lambda self, video_id, languages: TRANSCRIPT})(),
            metadata_fetcher=BrokenMetadata(),
        )
        with tempfile.TemporaryDirectory() as directory, self.assertRaises(WriteError):
            service.extract(VIDEO_ID, Path(directory), ExtractOptions())

    def test_output_directory_sync_precedes_done_and_queue_removal(self):
        events = []
        service = ExtractService(
            caption_acquirer=type("Captions", (), {"fetch": lambda self, video_id, languages: TRANSCRIPT})(),
            metadata_fetcher=Metadata(),
        )
        original_append = Ledger.append

        def recording_append(ledger, event):
            events.append(f"ledger:{event.status}")
            return original_append(ledger, event)

        from yt_extract_md.queue import QueueFile

        original_remove = QueueFile.remove_video

        def recording_remove(queue, video_id):
            events.append("queue:remove")
            return original_remove(queue, video_id)

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            queue = root / "queue.txt"
            queue.write_text(VIDEO_ID + "\n", encoding="utf-8")
            with (
                patch("yt_extract_md.output.fsync_directory", side_effect=lambda path: events.append("output:sync")),
                patch("yt_extract_md.service.Ledger.append", new=recording_append),
                patch("yt_extract_md.service.QueueFile.remove_video", new=recording_remove),
            ):
                code = Application(service, stderr=io.StringIO(), stdout=io.StringIO()).run_batch(
                    queue, root, ExtractOptions()
                )
            self.assertEqual(code, EXIT_OK)
            self.assertLess(events.index("output:sync"), events.index("ledger:DONE"))
            self.assertLess(events.index("ledger:DONE"), events.index("queue:remove"))

    def test_permanent_failure_is_failed_and_dequeued(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            queue = root / "queue.txt"
            queue.write_text(VIDEO_ID + "\n", encoding="utf-8")
            code = Application(FixedService(UnavailableError("private")), stderr=io.StringIO()).run_batch(
                queue, root, ExtractOptions()
            )
            self.assertEqual(code, EXIT_FAILED)
            self.assertEqual(queue.read_text(), "")
            self.assertEqual(Ledger(root).latest()[VIDEO_ID].status, "FAILED")

    def test_transient_attempt_cap_is_three_across_runs(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            queue = root / "queue.txt"
            queue.write_text(VIDEO_ID + "\n", encoding="utf-8")
            for expected in (1, 2, 3):
                code = Application(FixedService(FetchError("network")), stderr=io.StringIO()).run_batch(
                    queue, root, ExtractOptions()
                )
                self.assertEqual(code, EXIT_FAILED)
                self.assertEqual(Ledger(root).latest()[VIDEO_ID].attempts, expected)
                self.assertEqual(queue.read_text(), VIDEO_ID + "\n" if expected < 3 else "")
            self.assertEqual(Ledger(root).latest()[VIDEO_ID].status, "FAILED")

    def test_invalid_line_remains_and_does_not_block_valid_item(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            queue = root / "queue.txt"
            queue.write_text("bad line\n" + VIDEO_ID + "\n", encoding="utf-8")
            service = FixedService(TRANSCRIPT)
            code = Application(service, stderr=io.StringIO(), stdout=io.StringIO()).run_batch(queue, root, ExtractOptions())
            self.assertEqual(code, EXIT_FAILED)
            self.assertEqual(queue.read_text(), "bad line\n")

    def test_sleep_only_between_attempted_batch_videos(self):
        sleeps = []
        service = FixedService(TRANSCRIPT)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            queue = root / "queue.txt"
            queue.write_text(f"{VIDEO_ID}\n{OTHER_ID}\n", encoding="utf-8")
            code = Application(
                service,
                sleeper=sleeps.append,
                random_uniform=lambda low, high: 3.25,
                stdout=io.StringIO(),
                stderr=io.StringIO(),
            ).run_batch(queue, root, ExtractOptions())
            self.assertEqual(code, EXIT_OK)
            self.assertEqual(sleeps, [3.25])


if __name__ == "__main__":
    unittest.main()
