# yt-extract-md v2

`yt-extract-md` is a local Python 3.10+ CLI that saves YouTube captions as durable Markdown or plain-text files. It tries `youtube-transcript-api` first, then yt-dlp JSON3 captions. Optional Whisper fallback downloads temporary audio and transcribes it locally on the CPU. The program does not call an LLM, use a cloud transcription service, require an API key or account, or rewrite transcript wording.

## Prerequisites and installation

On macOS, install Python 3.10 or newer. `faster-whisper` uses PyAV for audio decoding; no separate `ffmpeg` executable is needed for this implementation.

From this checkout, create and activate a virtual environment, then choose one installation:

```sh
python3 -m venv .venv
source .venv/bin/activate

# Captions only
python3 -m pip install -c constraints.txt .

# Captions plus local Whisper fallback
python3 -m pip install -c constraints.txt '.[whisper]'
```

The core dependencies are exactly pinned to `youtube-transcript-api==1.2.4`, `yt-dlp==2026.7.4`, and `tenacity==9.1.4`. The `whisper` extra adds `faster-whisper==1.2.1`.

`constraints.txt` pins the audited full core and optional Whisper graph for reproducible source-checkout installs. It was resolved for Python 3.13 on macOS arm64; the project itself remains compatible with Python 3.10+. Maintainers must regenerate and audit the constraints when bumping dependencies.

## Commands

The output directory for `extract` and `batch` is mandatory. The CLI creates it automatically, including any missing parent directories.

```sh
yt-extract-md extract 0l3vUprzNzg --output-dir transcripts
yt-extract-md extract 'https://www.youtube.com/watch?v=ZAGbis1hfXw' --output-dir transcripts --format txt --no-timestamps
yt-extract-md extract 'https://youtu.be/hkyS0rLy1Uo' --output-dir transcripts --whisper-fallback

yt-extract-md enqueue urls.txt 0l3vUprzNzg ZAGbis1hfXw hkyS0rLy1Uo
yt-extract-md batch urls.txt --output-dir transcripts --whisper-fallback
```

These three video IDs are live-input examples supplied for the CLI; the offline test suite does not contact YouTube or assert that any current transcript is available.

Both extraction commands accept:

- `--format md|txt` (default `md`)
- timestamps by default, or `--no-timestamps`
- `--languages en,en-US,en-GB` as an ordered, comma-separated preference list
- `--whisper-fallback`
- `--whisper-model MODEL` (default `base`)

Inputs may be a canonical 11-character video ID or a YouTube watch, `youtu.be`, Shorts, embed, or `/v/` URL. Output filenames are flat: `<sanitized_title>_<video_id>.md` or `.txt`. Filename titles contain only safe ASCII characters and are capped near 80 characters; the video ID is always retained.

## Caption and Whisper behavior

Caption acquisition prefers manually created tracks in the configured language order, then generated tracks. If the first API has no usable captions, yt-dlp is tried for JSON3 subtitles. Source text is kept verbatim apart from caption transport markup/newlines and repeated leading text in yt-dlp rolling auto-caption cues. Start times are retained.

With `--whisper-fallback`, missing captions and caption-path IP blocks can fall back to local transcription. yt-dlp downloads best audio into an isolated temporary directory, and `faster-whisper` runs `WhisperModel(model_name, device="cpu", compute_type="int8")`; temporary audio is removed after success or failure. Models are downloaded by faster-whisper on first use and normally cached in the user's Hugging Face cache. Larger models take more disk, memory, and CPU time and may improve fidelity; `base` is the conservative default. Whisper output reflects model transcription and can differ from authored captions. If the optional package is absent, install it from this checkout with `python3 -m pip install -c constraints.txt '.[whisper]'`.

## Queue operation and concurrency

Queue files are UTF-8 text with one URL or ID per line. Blank lines and lines beginning with `#` are preserved. `enqueue` normalizes additions to canonical URLs, deduplicates by video ID, and writes under the same sidecar advisory lock used by every batch queue read/modify/write.

Batch selects each next item from a fresh locked read. When an item reaches `DONE`, permanent `FAILED`, or the transient-attempt cap, batch reacquires the lock, rereads the current file, and atomically removes every line that normalizes to that ID. Comments, blank lines, invalid lines, unrelated entries, and cooperatively enqueued entries are preserved. Invalid lines are reported and retained.

Direct queue edits are supported only while the batch and producers are idle. Concurrent producers must use `yt-extract-md enqueue`. Run only one batch consumer for a queue at a time; the producer lock prevents lost appends but is not a distributed job-claim system.

## Output and ledger schemas

Markdown starts with YAML frontmatter containing:

```text
video_id, video_url, title, channel, duration_seconds, published_at,
transcript_source, caption_kind, language, processed_at, extractor_version
```

String values are JSON-quoted, which is valid YAML. TXT files contain the same fields as a readable header. The body contains one source segment per line, prefixed by `[HH:MM:SS]` unless timestamps are disabled. Transcript files are written through a named temporary file in the output directory, flushed, fsynced, and atomically replaced.

Every recorded video state is appended to `<output-dir>/ledger.jsonl` as one JSON object:

```json
{"video_id":"0l3vUprzNzg","status":"DONE","reason":null,"source":"captions","processed_at":"2026-08-15T12:00:00Z","output_path":"transcripts/Example_0l3vUprzNzg.md","attempts":1}
```

`status` is `DONE`, `FAILED`, or `RETRYABLE`. `reason` is null on success or one of `INVALID_INPUT`, `UNAVAILABLE`, `MISSING_CAPTIONS`, `IP_BLOCKED`, `FETCH_ERROR`, `CONFIG_ERROR`, and `WRITE_ERROR`. `source` is `captions`, `whisper`, or null. Appends use an advisory lock and fsync. Blank ledger lines are ignored; malformed JSON stops with a clear error instead of being skipped. The latest record for a video controls idempotency and its next user-visible attempt number.

## Retries, batch stops, and exit codes

Transient network calls use bounded exponential retries internally. Those HTTP retries do not increment ledger attempts. Batch-run attempts are per video. `UNAVAILABLE` and missing captions without Whisper are permanent failures. `IP_BLOCKED` and `FETCH_ERROR` stay queued until three batch attempts; the third event is `FAILED` and the queue entry is removed. Batch continues past ordinary item failures and waits a random 2.0–4.5 seconds only between attempted videos.

An IP block stops the batch. If both caption paths are blocked and Whisper recovers the current item, batch first atomically writes the transcript, appends `DONE`, removes that item, then exits with the IP-block code while leaving every remaining entry untouched. If audio download is blocked or fails transiently, the appropriate retryable event is appended, the current entry remains unless it has reached the three-attempt cap, and the batch stops. Missing-caption recovery by Whisper does not stop a batch.

| Code | Constant | Meaning |
|---:|---|---|
| 0 | `EXIT_OK` | Requested work completed without ordinary failures |
| 1 | `EXIT_FAILED` | One or more ordinary/permanent item failures or retained invalid lines |
| 2 | `EXIT_USAGE` | Invalid input or command usage |
| 3 | `EXIT_IP_BLOCKED` | Batch stopped because of an IP block, including a recovered current item |
| 4 | `EXIT_CONFIG` | Required core/optional configuration is missing |
| 5 | `EXIT_WRITE` | Output, queue, or ledger storage failed |

## Scheduling

For cron or `launchd`, activate the intended virtual environment by using the absolute installed command path, use absolute queue/output paths, capture stdout/stderr, and prevent overlapping batch consumers. Treat exit code 3 as a backoff signal rather than immediately restarting. Producers can safely call `enqueue` while a batch runs.

## Offline verification

The test suite uses only `unittest`, mocks, and fakes. It does not access YouTube, download audio/models, or sleep:

```sh
PYTHONPATH=src python3 -m unittest discover -s tests -v
PYTHONPATH=src python3 -m yt_extract_md --help
python3 -m compileall -q src tests
git diff --check
git status --short
```

Live YouTube behavior still depends on current video availability, captions, network/IP reputation, yt-dlp compatibility, and (when selected) local model download/cache state.
