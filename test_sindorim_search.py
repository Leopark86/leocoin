"""
sindorim_search.py 단위 테스트
YouTube API 키 없이도 핵심 로직을 검증합니다.
"""

import unittest
from unittest.mock import MagicMock, patch

from sindorim_search import (
    DEFAULT_KEYWORDS,
    Mention,
    VideoResult,
    find_keyword_in_transcript,
    search_keyword_mentions,
)


class TestDefaultKeywords(unittest.TestCase):
    def test_default_keywords_contains_three(self):
        self.assertEqual(len(DEFAULT_KEYWORDS), 3)

    def test_default_keywords_values(self):
        self.assertIn("신도림4차", DEFAULT_KEYWORDS)
        self.assertIn("신도림이편한세상", DEFAULT_KEYWORDS)
        self.assertIn("신도림대장", DEFAULT_KEYWORDS)


class TestMention(unittest.TestCase):
    def test_timestamp_str_seconds_only(self):
        m = Mention(timestamp_sec=45.0, text="신도림4차 근처")
        self.assertEqual(m.timestamp_str, "00:45")

    def test_timestamp_str_minutes(self):
        m = Mention(timestamp_sec=125.0, text="신도림이편한세상 환승")
        self.assertEqual(m.timestamp_str, "02:05")

    def test_timestamp_str_hours(self):
        m = Mention(timestamp_sec=3661.0, text="신도림대장 도착")
        self.assertEqual(m.timestamp_str, "01:01:01")

    def test_youtube_url_timestamp(self):
        m = Mention(timestamp_sec=90.0, text="신도림4차")
        self.assertEqual(m.youtube_url_timestamp, "?t=90s")


class TestVideoResult(unittest.TestCase):
    def setUp(self):
        self.video = VideoResult(
            video_id="abc123",
            title="서울 부동산 투어",
            channel="부동산채널",
            published_at="2024-01-15",
            keyword="신도림4차",
            mentions=[
                Mention(timestamp_sec=60.0, text="신도림4차에서"),
                Mention(timestamp_sec=300.0, text="신도림4차 단지"),
            ],
        )

    def test_video_url(self):
        self.assertEqual(
            self.video.video_url, "https://www.youtube.com/watch?v=abc123"
        )

    def test_mention_url(self):
        url = self.video.mention_url(self.video.mentions[0])
        self.assertEqual(url, "https://www.youtube.com/watch?v=abc123&t=60s")

    def test_mention_count(self):
        self.assertEqual(len(self.video.mentions), 2)

    def test_keyword_stored(self):
        self.assertEqual(self.video.keyword, "신도림4차")


class TestFindKeywordInTranscript(unittest.TestCase):
    @patch("sindorim_search.YouTubeTranscriptApi")
    def test_finds_keyword_mentions(self, mock_api):
        mock_transcript = MagicMock()
        mock_transcript.fetch.return_value = [
            {"start": 10.0, "duration": 3.0, "text": "오늘은 신도림4차 아파트를 방문합니다"},
            {"start": 45.0, "duration": 3.0, "text": "여기는 강남입니다"},
            {"start": 120.0, "duration": 3.0, "text": "신도림4차 단지 내부입니다"},
        ]
        mock_api.list_transcripts.return_value.find_transcript.return_value = (
            mock_transcript
        )

        mentions = find_keyword_in_transcript("test_id", "신도림4차")

        self.assertEqual(len(mentions), 2)
        self.assertEqual(mentions[0].timestamp_sec, 10.0)
        self.assertEqual(mentions[1].timestamp_sec, 120.0)

    @patch("sindorim_search.YouTubeTranscriptApi")
    def test_finds_different_keyword(self, mock_api):
        mock_transcript = MagicMock()
        mock_transcript.fetch.return_value = [
            {"start": 5.0, "duration": 2.0, "text": "신도림이편한세상 입니다"},
            {"start": 30.0, "duration": 2.0, "text": "신도림대장 아파트"},
        ]
        mock_api.list_transcripts.return_value.find_transcript.return_value = (
            mock_transcript
        )

        mentions_ecl = find_keyword_in_transcript("test_id", "신도림이편한세상")
        mentions_dj = find_keyword_in_transcript("test_id", "신도림대장")

        self.assertEqual(len(mentions_ecl), 1)
        self.assertEqual(len(mentions_dj), 1)

    @patch("sindorim_search.YouTubeTranscriptApi")
    def test_no_keyword_returns_empty(self, mock_api):
        mock_transcript = MagicMock()
        mock_transcript.fetch.return_value = [
            {"start": 5.0, "duration": 2.0, "text": "안녕하세요"},
            {"start": 10.0, "duration": 2.0, "text": "오늘의 주제는 강남입니다"},
        ]
        mock_api.list_transcripts.return_value.find_transcript.return_value = (
            mock_transcript
        )

        for kw in DEFAULT_KEYWORDS:
            mentions = find_keyword_in_transcript("test_id", kw)
            self.assertEqual(mentions, [])

    @patch("sindorim_search.YouTubeTranscriptApi")
    def test_transcripts_disabled_returns_empty(self, mock_api):
        from youtube_transcript_api import TranscriptsDisabled

        mock_api.list_transcripts.side_effect = TranscriptsDisabled("test_id")
        for kw in DEFAULT_KEYWORDS:
            mentions = find_keyword_in_transcript("test_id", kw)
            self.assertEqual(mentions, [])


class TestSearchKeywordMentions(unittest.TestCase):
    @patch("sindorim_search.find_keyword_in_transcript")
    def test_filters_videos_with_mentions(self, mock_find):
        video_list = [
            {
                "video_id": "vid1",
                "title": "서울 부동산 트렌드",
                "channel": "채널A",
                "published_at": "2024-01-01",
            },
            {
                "video_id": "vid2",
                "title": "부산 여행",
                "channel": "채널B",
                "published_at": "2024-02-01",
            },
            {
                "video_id": "vid3",
                "title": "신도림4차 완전정복",
                "channel": "채널C",
                "published_at": "2024-03-01",
            },
        ]

        def side_effect(video_id, keyword):
            if video_id == "vid1":
                return [Mention(30.0, "신도림4차 지나쳐")]
            if video_id == "vid3":
                return [
                    Mention(10.0, "신도림4차입니다"),
                    Mention(60.0, "신도림4차 출구"),
                ]
            return []

        mock_find.side_effect = side_effect

        results = search_keyword_mentions(video_list, "신도림4차", delay=0)

        self.assertEqual(len(results), 2)
        self.assertEqual(results[0].video_id, "vid1")
        self.assertEqual(results[1].video_id, "vid3")
        self.assertEqual(len(results[1].mentions), 2)
        self.assertTrue(all(r.keyword == "신도림4차" for r in results))

    @patch("sindorim_search.find_keyword_in_transcript")
    def test_each_keyword_tagged_correctly(self, mock_find):
        video_list = [
            {
                "video_id": "vid1",
                "title": "부동산 영상",
                "channel": "채널A",
                "published_at": "2024-01-01",
            }
        ]

        for keyword in DEFAULT_KEYWORDS:
            mock_find.return_value = [Mention(10.0, f"{keyword} 언급")]
            results = search_keyword_mentions(video_list, keyword, delay=0)
            self.assertEqual(len(results), 1)
            self.assertEqual(results[0].keyword, keyword)


if __name__ == "__main__":
    unittest.main(verbosity=2)
