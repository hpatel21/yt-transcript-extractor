import errno
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from yt_extract_md.errors import WriteError
from yt_extract_md.models import Segment, Transcript, VideoMetadata
from yt_extract_md.output import (
    atomic_write,
    output_filename,
    render_markdown,
    render_text,
    sanitize_title,
    validate_output_dir,
)


class OutputTests(unittest.TestCase):
    def setUp(self):
        self.metadata = VideoMetadata('A "quoted": title', "Channel", 65, "2026-01-02")
        self.transcript = Transcript((Segment("first  text", 1.9), Segment("second", 3661)), "captions", "manual", "en")

    def test_markdown_and_text_rendering(self):
        markdown = render_markdown("0l3vUprzNzg", self.metadata, self.transcript, "2026-08-15T00:00:00Z")
        self.assertIn('title: "A \\"quoted\\": title"', markdown)
        self.assertIn("duration_seconds: 65", markdown)
        self.assertIn("[00:00:01] first  text\n[01:01:01] second\n", markdown)
        plain = render_text(
            "0l3vUprzNzg", self.metadata, self.transcript, "2026-08-15T00:00:00Z", timestamps=False
        )
        self.assertIn("Transcript source: captions", plain)
        self.assertTrue(plain.endswith("first  text\nsecond\n"))

    def test_sanitization_strips_forbidden_non_ascii_and_caps_title(self):
        value = sanitize_title("  héllo / 😀 : world___ " + "x" * 100)
        self.assertEqual(value[:10], "hllo_world")
        self.assertLessEqual(len(value), 80)
        filename = output_filename("😀", "0l3vUprzNzg", "md")
        self.assertEqual(filename, "video_0l3vUprzNzg.md")

    def test_atomic_write_cleans_temp_after_replace_error(self):
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "out.md"
            with patch("yt_extract_md.output.os.replace", side_effect=OSError("boom")):
                with self.assertRaises(WriteError):
                    atomic_write(destination, "data")
            self.assertEqual(list(Path(directory).iterdir()), [])

    def test_atomic_write_syncs_parent_directory_after_replace(self):
        events = []
        real_replace = os.replace

        def recording_replace(source, destination):
            real_replace(source, destination)
            events.append("replace")

        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "out.md"
            with (
                patch("yt_extract_md.output.os.replace", side_effect=recording_replace),
                patch("yt_extract_md.output.fsync_directory", side_effect=lambda path: events.append("directory fsync")),
            ):
                atomic_write(destination, "data")
        self.assertEqual(events, ["replace", "directory fsync"])

    def test_atomic_write_surfaces_directory_sync_failure_without_temp_leak(self):
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "out.md"
            with patch("yt_extract_md.output.fsync_directory", side_effect=WriteError("directory fsync failed")):
                with self.assertRaisesRegex(WriteError, "directory fsync failed"):
                    atomic_write(destination, "data")
            self.assertEqual(list(Path(directory).iterdir()), [destination])

    def test_directory_sync_surfaces_genuine_open_failure(self):
        from yt_extract_md.output import fsync_directory

        with patch("yt_extract_md.output.os.open", side_effect=OSError(errno.EIO, "I/O error")):
            with self.assertRaisesRegex(WriteError, "Could not open directory"):
                fsync_directory(Path("unused"))

    def test_output_directory_must_exist_and_be_writable(self):
        with tempfile.TemporaryDirectory() as directory:
            self.assertEqual(validate_output_dir(directory), Path(directory))
            with self.assertRaises(WriteError):
                validate_output_dir(Path(directory) / "missing")
            with patch("yt_extract_md.output.os.access", return_value=False), self.assertRaises(WriteError):
                validate_output_dir(directory)


if __name__ == "__main__":
    unittest.main()
