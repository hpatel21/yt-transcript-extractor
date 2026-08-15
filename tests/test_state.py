import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from yt_extract_md.errors import WriteError
from yt_extract_md.ledger import Ledger, LedgerEvent
from yt_extract_md.models import LedgerStatus, Reason
from yt_extract_md.queue import QueueFile


class StateTests(unittest.TestCase):
    def test_ledger_is_append_only_and_latest_wins(self):
        with tempfile.TemporaryDirectory() as directory:
            ledger = Ledger(Path(directory))
            ledger.append(LedgerEvent.create("0l3vUprzNzg", LedgerStatus.RETRYABLE, Reason.FETCH_ERROR, None, "a", None, 1))
            ledger.append(LedgerEvent.create("0l3vUprzNzg", LedgerStatus.DONE, None, "captions", "b", "out.md", 2))
            self.assertEqual(len(ledger.read_events()), 2)
            latest = ledger.latest()["0l3vUprzNzg"]
            self.assertEqual((latest.status, latest.attempts), ("DONE", 2))
            self.assertEqual(len(ledger.path.read_text().splitlines()), 2)

    def test_blank_ledger_lines_are_skipped_but_malformed_json_fails(self):
        with tempfile.TemporaryDirectory() as directory:
            ledger = Ledger(Path(directory))
            ledger.path.write_text("\n{not-json}\n", encoding="utf-8")
            with self.assertRaisesRegex(WriteError, "Malformed ledger JSON"):
                ledger.latest()

    def test_queue_removal_rereads_and_preserves_concurrent_append_and_invalid(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "queue.txt"
            path.write_text("# note\n0l3vUprzNzg\nbad line\n", encoding="utf-8")
            queue = QueueFile(path)
            queue.snapshot()
            with path.open("a", encoding="utf-8") as handle:
                handle.write("ZAGbis1hfXw\n")
            self.assertEqual(queue.remove_video("0l3vUprzNzg"), 1)
            self.assertEqual(path.read_text(), "# note\nbad line\nZAGbis1hfXw\n")

    def test_enqueue_canonicalizes_and_deduplicates(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "queue.txt"
            path.write_text("# queue\n0l3vUprzNzg\n", encoding="utf-8")
            added = QueueFile(path).enqueue(
                ["https://youtu.be/0l3vUprzNzg", "https://youtube.com/shorts/ZAGbis1hfXw", "ZAGbis1hfXw"]
            )
            self.assertEqual(added, ["ZAGbis1hfXw"])
            self.assertEqual(path.read_text().count("ZAGbis1hfXw"), 1)
            self.assertIn("https://www.youtube.com/watch?v=ZAGbis1hfXw", path.read_text())

    def test_queue_replace_syncs_parent_directory_after_replace(self):
        events = []
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "queue.txt"
            path.write_text("0l3vUprzNzg\n", encoding="utf-8")
            real_replace = __import__("os").replace

            def recording_replace(source, destination):
                real_replace(source, destination)
                events.append("replace")

            with (
                patch("yt_extract_md.queue.os.replace", side_effect=recording_replace),
                patch("yt_extract_md.queue.fsync_directory", side_effect=lambda parent: events.append("directory fsync")),
            ):
                QueueFile(path).remove_video("0l3vUprzNzg")
        self.assertEqual(events, ["replace", "directory fsync"])

    def test_ledger_syncs_file_before_output_directory(self):
        events = []
        with tempfile.TemporaryDirectory() as directory:
            ledger = Ledger(Path(directory))
            event = LedgerEvent.create(
                "0l3vUprzNzg", LedgerStatus.DONE, None, "captions", "now", "out.md", 1
            )
            with (
                patch("yt_extract_md.ledger.os.fsync", side_effect=lambda descriptor: events.append("file fsync")),
                patch(
                    "yt_extract_md.ledger.fsync_directory",
                    side_effect=lambda parent: events.append("directory fsync"),
                ),
            ):
                ledger.append(event)
        self.assertEqual(events, ["file fsync", "directory fsync"])


if __name__ == "__main__":
    unittest.main()
