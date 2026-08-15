import json
import sys
import types
import unittest
from unittest.mock import patch

from yt_extract_md.captions import (
    CaptionAcquirer,
    YouTubeTranscriptApiFetcher,
    _select_json3_track,
    classify_fetch_exception,
    remove_rolling_prefix,
    transcript_from_json3,
)
from yt_extract_md.errors import ConfigError, FetchError, IpBlockedError, MissingCaptionsError, UnavailableError


class FakeTrack:
    language_code = "en-US"
    is_generated = False

    def fetch(self):
        return [{"text": "verbatim  text", "start": 1.25}]


class FakeList:
    def __init__(self):
        self.calls = []

    def find_manually_created_transcript(self, languages):
        self.calls.append(("manual", languages))
        return FakeTrack()

    def find_generated_transcript(self, languages):
        self.calls.append(("generated", languages))
        raise AssertionError("generated should not be considered when manual exists")


class CaptionTests(unittest.TestCase):
    def test_manual_is_selected_before_generated_in_language_order(self):
        transcript_list = FakeList()

        class Api:
            def list(self, video_id):
                self.video_id = video_id
                return transcript_list

        module = types.SimpleNamespace(YouTubeTranscriptApi=Api)
        with patch.dict(sys.modules, {"youtube_transcript_api": module}):
            result = YouTubeTranscriptApiFetcher(retry_call=lambda operation: operation()).fetch(
                "0l3vUprzNzg", ("en-US", "en")
            )
        self.assertEqual(transcript_list.calls, [("manual", ["en-US", "en"])])
        self.assertEqual(result.caption_kind, "manual")
        self.assertEqual(result.segments[0].text, "verbatim  text")

    def test_json3_rolling_overlap_only_removes_repeated_prefix(self):
        payload = {
            "events": [
                {"tStartMs": 1000, "segs": [{"utf8": "hello world"}]},
                {"tStartMs": 2000, "segs": [{"utf8": "hello world again"}]},
                {"tStartMs": 3000, "segs": [{"utf8": "different hello world"}]},
            ]
        }
        result = transcript_from_json3(json.dumps(payload), "en", generated=True)
        self.assertEqual([segment.text for segment in result.segments], ["hello world", "again", "different hello world"])
        self.assertEqual([segment.start for segment in result.segments], [1.0, 2.0, 3.0])
        self.assertEqual(remove_rolling_prefix("alpha beta", "gamma alpha beta"), "gamma alpha beta")

    def test_json3_manual_does_not_dedupe(self):
        payload = {"events": [{"tStartMs": 0, "segs": [{"utf8": "same"}]}, {"tStartMs": 1, "segs": [{"utf8": "same"}]}]}
        result = transcript_from_json3(payload, "en", generated=False)
        self.assertEqual([segment.text for segment in result.segments], ["same", "same"])

    def test_json3_natural_prefix_collision_is_preserved(self):
        payload = {
            "events": [
                {"tStartMs": 0, "segs": [{"utf8": "the cat"}]},
                {"tStartMs": 1, "segs": [{"utf8": "the dog"}]},
            ]
        }
        result = transcript_from_json3(payload, "en", generated=True)
        self.assertEqual([segment.text for segment in result.segments], ["the cat", "the dog"])

    def test_json3_single_token_suffix_collision_is_preserved(self):
        self.assertEqual(remove_rolling_prefix("we saw the", "the dog ran"), "the dog ran")

    def test_yt_dlp_track_selection_respects_language_order(self):
        tracks = {
            "en": [{"ext": "json3", "url": "en-url"}],
            "fr": [{"ext": "vtt", "url": "ignored"}, {"ext": "json3", "url": "fr-url"}],
        }
        self.assertEqual(_select_json3_track(tracks, ("fr", "en")), ("fr", tracks["fr"][1]))

    def test_both_ip_blocks_are_distinguished(self):
        class Blocked:
            def fetch(self, video_id, languages):
                raise IpBlockedError("blocked")

        with self.assertRaises(IpBlockedError) as raised:
            CaptionAcquirer(Blocked(), Blocked()).fetch("0l3vUprzNzg", ("en",))
        self.assertTrue(raised.exception.both_caption_paths_blocked)

    def test_any_caption_ip_block_takes_precedence_over_mixed_provider_failure(self):
        class Raises:
            def __init__(self, error):
                self.error = error

            def fetch(self, video_id, languages):
                raise self.error

        for secondary_error in (
            MissingCaptionsError("missing"),
            FetchError("network"),
            UnavailableError("removed"),
            ConfigError("secondary unavailable"),
        ):
            with self.subTest(secondary_error=type(secondary_error).__name__):
                with self.assertRaises(IpBlockedError) as raised:
                    CaptionAcquirer(Raises(IpBlockedError("blocked")), Raises(secondary_error)).fetch(
                        "0l3vUprzNzg", ("en",)
                    )
                self.assertFalse(raised.exception.both_caption_paths_blocked)

    def test_wrapped_yt_dlp_permanent_messages_are_unavailable(self):
        DownloadError = type("DownloadError", (Exception,), {})
        for message in (
            "Video unavailable",
            "PRIVATE VIDEO",
            "This video is private",
            "This video has been removed by the uploader",
            "This video is not available in your country",
        ):
            with self.subTest(message=message):
                result = classify_fetch_exception(DownloadError(message), "yt-dlp")
                self.assertIsInstance(result, UnavailableError)

    def test_explicit_block_evidence_precedes_permanent_message(self):
        DownloadError = type("DownloadError", (Exception,), {})
        result = classify_fetch_exception(DownloadError("HTTP Error 429: Video unavailable"), "yt-dlp")
        self.assertIsInstance(result, IpBlockedError)

    def test_ordinary_network_and_generic_login_errors_remain_fetch_errors(self):
        DownloadError = type("DownloadError", (Exception,), {})
        for message in ("Connection reset by peer", "Sign in to continue", "Sign in to confirm your age"):
            with self.subTest(message=message):
                result = classify_fetch_exception(DownloadError(message), "yt-dlp")
                self.assertIsInstance(result, FetchError)

    def test_known_youtube_bot_challenge_is_ip_blocked(self):
        DownloadError = type("DownloadError", (Exception,), {})
        result = classify_fetch_exception(
            DownloadError("Sign in to confirm you're not a bot. This helps protect our community."), "yt-dlp"
        )
        self.assertIsInstance(result, IpBlockedError)

    def test_missing_from_both_is_missing(self):
        class Missing:
            def fetch(self, video_id, languages):
                raise MissingCaptionsError("missing")

        with self.assertRaises(MissingCaptionsError):
            CaptionAcquirer(Missing(), Missing()).fetch("0l3vUprzNzg", ("en",))


if __name__ == "__main__":
    unittest.main()
