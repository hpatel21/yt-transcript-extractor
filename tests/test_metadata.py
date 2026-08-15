import unittest
from unittest.mock import patch

from yt_extract_md.metadata import MetadataFetcher


VIDEO_ID = "0l3vUprzNzg"


class Response:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return False

    def read(self):
        return self.payload


class MetadataTests(unittest.TestCase):
    def test_oembed_non_object_json_returns_defaults(self):
        with patch("yt_extract_md.metadata.urlopen", return_value=Response(b"[]")):
            result = MetadataFetcher()._oembed(VIDEO_ID)
        self.assertEqual((result.title, result.channel), (f"Video {VIDEO_ID}", "Unknown"))

    def test_oembed_malformed_json_returns_defaults(self):
        with patch("yt_extract_md.metadata.urlopen", return_value=Response(b"{")):
            result = MetadataFetcher()._oembed(VIDEO_ID)
        self.assertEqual(result.title, f"Video {VIDEO_ID}")

    def test_oembed_timeout_returns_defaults(self):
        with patch("yt_extract_md.metadata.urlopen", side_effect=TimeoutError("timed out")):
            result = MetadataFetcher()._oembed(VIDEO_ID)
        self.assertEqual(result.title, f"Video {VIDEO_ID}")


if __name__ == "__main__":
    unittest.main()
