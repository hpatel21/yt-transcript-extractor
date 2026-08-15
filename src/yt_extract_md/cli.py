from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Callable, Sequence

from . import __version__
from .errors import ConfigError, InvalidInputError, WriteError
from .output import validate_output_dir
from .queue import QueueFile
from .service import Application, EXIT_CONFIG, EXIT_FAILED, EXIT_OK, EXIT_USAGE, EXIT_WRITE, ExtractOptions


DEFAULT_LANGUAGES = "en,en-US,en-GB"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="yt-extract-md", description="Extract YouTube transcripts to Markdown or text")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    subparsers = parser.add_subparsers(dest="command", required=True)

    def add_extract_options(command: argparse.ArgumentParser) -> None:
        command.add_argument("--output-dir", required=True, type=Path, help="existing writable output directory")
        command.add_argument("--format", choices=("md", "txt"), default="md")
        command.add_argument("--no-timestamps", action="store_true")
        command.add_argument("--languages", default=DEFAULT_LANGUAGES, help="comma-separated preferred language codes")
        command.add_argument("--whisper-fallback", action="store_true")
        command.add_argument("--whisper-model", default="base")

    extract = subparsers.add_parser("extract", help="extract one video")
    extract.add_argument("url_or_id")
    add_extract_options(extract)

    batch = subparsers.add_parser("batch", help="process a locked queue file")
    batch.add_argument("queue_file", type=Path)
    add_extract_options(batch)

    enqueue = subparsers.add_parser("enqueue", help="append canonical, deduplicated videos to a queue")
    enqueue.add_argument("queue_file", type=Path)
    enqueue.add_argument("url_or_id", nargs="+")
    return parser


def _options(args: argparse.Namespace) -> ExtractOptions:
    languages = tuple(item.strip() for item in args.languages.split(",") if item.strip())
    if not languages:
        raise InvalidInputError("At least one preferred language is required")
    return ExtractOptions(args.format, not args.no_timestamps, languages, args.whisper_fallback, args.whisper_model)


def main(argv: Sequence[str] | None = None, application_factory: Callable[[], Application] = Application) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "enqueue":
        try:
            added = QueueFile(args.queue_file).enqueue(args.url_or_id)
            print(f"Enqueued {len(added)} video(s)")
            return EXIT_OK
        except InvalidInputError as exc:
            print(f"INVALID_INPUT: {exc}", file=sys.stderr)
            return EXIT_USAGE
        except WriteError as exc:
            print(f"WRITE_ERROR: {exc}", file=sys.stderr)
            return EXIT_WRITE
    try:
        output_dir = validate_output_dir(args.output_dir)
        options = _options(args)
    except InvalidInputError as exc:
        print(f"INVALID_INPUT: {exc}", file=sys.stderr)
        return EXIT_USAGE
    except WriteError as exc:
        print(f"WRITE_ERROR: {exc}", file=sys.stderr)
        return EXIT_WRITE
    try:
        app = application_factory()
        if args.command == "extract":
            return app.run_extract(args.url_or_id, output_dir, options)
        return app.run_batch(args.queue_file, output_dir, options)
    except KeyboardInterrupt:
        print("Interrupted", file=sys.stderr)
        return EXIT_FAILED
    except ConfigError as exc:
        print(f"CONFIG_ERROR: {exc}", file=sys.stderr)
        return EXIT_CONFIG


def entrypoint() -> None:
    raise SystemExit(main())
