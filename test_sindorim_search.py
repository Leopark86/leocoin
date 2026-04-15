"""
sindorim_search.py 단위 테스트
YouTube API 키 없이도 핵심 로직을 검증합니다.
"""

import unittest
from unittest.mock import MagicMock, patch

from sindorim_search import (
    Mention,
    VideoResult,
    find_keyword_in_transcript,
    search_sindorim_mentions,
)


class TestMention(unittest.TestCase):
    def test_timestamp_str_seconds_only(self):
        m = Mention(timestamp_sec=45.0, text="신도림역 근처")
        self.assertEqual(m.timestamp_str, "00:45")

    def test_timestamp_str_minutes(self):
        m = Mention(timestamp_sec=125.0, text="신도림 환승")
        self.assertEqual(m.timestamp_str, "02:05")

    def test_timestamp_str_hours(self):
        m = Mention(timestamp_sec=3661.0, text="신도림 도착")
        self.assertEqual(m.timestamp_str, "01:01:01")

    def test_youtube_url_timestamp(self):
        m = Mention(timestamp_sec=90.0, text="신도림")
        self.assertEqual(m.youtube_url_timestamp, "?t=90s")


class TestVideoResult(unittest.TestCase):
    def setUp(self):
        self.video = VideoResult(
            video_id="abc123",
            title="서울 지하철 투어",
            channel="여행채널",
            published_at="2024-01-15",
            mentions=[
                Mention(timestamp_sec=60.0, text="신도림역에서"),
                Mention(timestamp_sec=300.0, text="신도림 환승"),
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


class TestFindKeywordInTranscript(unittest.TestCase):
    @patch("sindorim_search.YouTubeTranscriptApi")
    def test_finds_keyword_mentions(self, mock_api):
        mock_transcript = MagicMock()
        mock_transcript.fetch.return_value = [
            {"start": 10.0, "duration": 3.0, "text": "오늘은 신도림역을 방문합니다"},
            {"start": 45.0, "duration": 3.0, "text": "여기는 강남입니다"},
            {"start": 120.0, "duration": 3.0, "text": "신도림 환승 구조를 설명합니다"},
        ]
        mock_api.list_transcripts.return_value.find_transcript.return_value = (
            mock_transcript
        )

        mentions = find_keyword_in_transcript("test_id", "신도림")

        self.assertEqual(len(mentions), 2)
        self.assertEqual(mentions[0].timestamp_sec, 10.0)
        self.assertEqual(mentions[1].timestamp_sec, 120.0)

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

        mentions = find_keyword_in_transcript("test_id", "신도림")
        self.assertEqual(len(mentions), 0)

    @patch("sindorim_search.YouTubeTranscriptApi")
    def test_transcripts_disabled_returns_empty(self, mock_api):
        from youtube_transcript_api import TranscriptsDisabled

        mock_api.list_transcripts.side_effect = TranscriptsDisabled("test_id")
        mentions = find_keyword_in_transcript("test_id", "신도림")
        self.assertEqual(mentions, [])


class TestSearchSindorimMentions(unittest.TestCase):
    @patch("sindorim_search.find_keyword_in_transcript")
    def test_filters_videos_with_mentions(self, mock_find):
        video_list = [
            {
                "video_id": "vid1",
                "title": "서울 지하철 2호선",
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
                "title": "신도림역 완전정복",
                "channel": "채널C",
                "published_at": "2024-03-01",
            },
        ]

        def side_effect(video_id, keyword):
            if video_id == "vid1":
                return [Mention(30.0, "신도림 지나쳐")]
            if video_id == "vid3":
                return [
                    Mention(10.0, "신도림역입니다"),
                    Mention(60.0, "신도림 출구"),
                ]
            return []

        mock_find.side_effect = side_effect

        results = search_sindorim_mentions(video_list, "신도림", delay=0)

        self.assertEqual(len(results), 2)
        self.assertEqual(results[0].video_id, "vid1")
        self.assertEqual(results[1].video_id, "vid3")
        self.assertEqual(len(results[1].mentions), 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
