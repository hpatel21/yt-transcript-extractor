import unittest

from yt_extract_md.errors import InvalidInputError
from yt_extract_md.urls import canonical_url, normalize_video_id


class UrlTests(unittest.TestCase):
    def test_supported_forms(self):
        video_id = "0l3vUprzNzg"
        values = [
            video_id,
            f"https://www.youtube.com/watch?v={video_id}",
            f"https://www.youtube.com/watch?list=PL123&v={video_id}&t=12",
            f"https://youtu.be/{video_id}?si=abc",
            f"https://youtube.com/shorts/{video_id}?feature=share",
            f"https://www.youtube.com/embed/{video_id}",
            f"https://m.youtube.com/v/{video_id}",
        ]
        for value in values:
            with self.subTest(value=value):
                self.assertEqual(normalize_video_id(value), video_id)
        self.assertEqual(canonical_url(video_id), f"https://www.youtube.com/watch?v={video_id}")

    def test_rejections(self):
        values = [
            "short",
            "https://example.com/watch?v=0l3vUprzNzg",
            "https://notyoutube.com/watch?v=0l3vUprzNzg",
            "https://youtube.com/playlist?list=abc",
            "https://youtu.be/0l3vUprzNzg/extra",
            "https://youtube.com/watch?v=0l3vUprzNzgXX",
            "javascript:0l3vUprzNzg",
        ]
        for value in values:
            with self.subTest(value=value), self.assertRaises(InvalidInputError):
                normalize_video_id(value)


if __name__ == "__main__":
    unittest.main()

