import builtins
import io
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

from yt_extract_md.cli import build_parser, main
from yt_extract_md.errors import ConfigError, FetchError
from yt_extract_md.service import EXIT_OK, EXIT_USAGE, EXIT_WRITE
from yt_extract_md.whisper import WhisperFetcher


class FakeApplication:
    def __init__(self):
        self.extract_call = None
        self.batch_call = None

    def run_extract(self, value, output_dir, options):
        self.extract_call = (value, output_dir, options)
        return EXIT_OK

    def run_batch(self, queue, output_dir, options):
        self.batch_call = (queue, output_dir, options)
        return EXIT_OK


class CliWhisperTests(unittest.TestCase):
    def test_help_parses_without_third_party_dependencies(self):
        with self.assertRaises(SystemExit) as raised, patch("sys.stdout", new=io.StringIO()):
            build_parser().parse_args(["--help"])
        self.assertEqual(raised.exception.code, 0)

    def test_cli_passes_extract_options_and_exit_code(self):
        fake = FakeApplication()
        with tempfile.TemporaryDirectory() as directory:
            code = main(
                [
                    "extract",
                    "0l3vUprzNzg",
                    "--output-dir",
                    directory,
                    "--format",
                    "txt",
                    "--no-timestamps",
                    "--languages",
                    "fr,en",
                    "--whisper-fallback",
                    "--whisper-model",
                    "small",
                ],
                application_factory=lambda: fake,
            )
        self.assertEqual(code, EXIT_OK)
        options = fake.extract_call[2]
        self.assertEqual((options.output_format, options.timestamps, options.languages), ("txt", False, ("fr", "en")))
        self.assertTrue(options.whisper_fallback)
        self.assertEqual(options.whisper_model, "small")

    def test_missing_output_directory_is_write_exit(self):
        code = main(
            ["extract", "0l3vUprzNzg", "--output-dir", "/definitely/not/here"],
            application_factory=FakeApplication,
        )
        self.assertEqual(code, EXIT_WRITE)

    def test_empty_languages_is_usage_exit(self):
        with tempfile.TemporaryDirectory() as directory:
            code = main(
                ["extract", "0l3vUprzNzg", "--output-dir", directory, "--languages", ","],
                application_factory=FakeApplication,
            )
        self.assertEqual(code, EXIT_USAGE)

    def test_enqueue_cli_canonicalizes(self):
        with tempfile.TemporaryDirectory() as directory:
            queue = Path(directory) / "queue.txt"
            code = main(["enqueue", str(queue), "https://youtu.be/0l3vUprzNzg"])
            self.assertEqual(code, EXIT_OK)
            self.assertEqual(queue.read_text(), "https://www.youtube.com/watch?v=0l3vUprzNzg\n")

    def test_missing_whisper_dependency_is_actionable_config_error(self):
        original_import = builtins.__import__

        def rejecting_import(name, *args, **kwargs):
            if name == "faster_whisper":
                raise ModuleNotFoundError(name)
            return original_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=rejecting_import):
            with self.assertRaisesRegex(ConfigError, r"install with: python3 -m pip install '\.\[whisper\]'"):
                WhisperFetcher().fetch("0l3vUprzNzg", "base")

    def test_whisper_uses_cpu_int8_and_cleans_temp_audio_after_failure(self):
        observed = {}

        class FakeYdl:
            def __init__(self, options):
                self.options = options

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def extract_info(self, url, download):
                audio = Path(self.options["outtmpl"].replace("%(ext)s", "m4a"))
                audio.write_bytes(b"audio")
                observed["audio"] = audio
                return {"requested_downloads": [{"filepath": str(audio)}]}

        class FakeModel:
            def __init__(self, name, device, compute_type):
                observed["model"] = (name, device, compute_type)

            def transcribe(self, path):
                self.path = path
                raise RuntimeError("model failed")

        modules = {
            "yt_dlp": types.SimpleNamespace(YoutubeDL=FakeYdl),
            "faster_whisper": types.SimpleNamespace(WhisperModel=FakeModel),
        }
        with patch.dict("sys.modules", modules), self.assertRaises(FetchError):
            WhisperFetcher(retry_call=lambda operation: operation()).fetch("0l3vUprzNzg", "small")
        self.assertEqual(observed["model"], ("small", "cpu", "int8"))
        self.assertFalse(observed["audio"].parent.exists())


if __name__ == "__main__":
    unittest.main()
