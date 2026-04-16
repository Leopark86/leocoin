"""
sindorim_search.py 단위 테스트
YouTube API 키 없이도 핵심 로직을 검증합니다.
"""

import unittest
from unittest.mock import MagicMock, patch

from sindorim_search import (
    DEFAULT_KEYWORDS,
    KEYWORD_MAP,
    Mention,
    VideoResult,
    find_keywords_in_transcript,
    search_keyword_mentions,
    _transcript_api,
)


class TestDefaultKeywords(unittest.TestCase):
    def test_default_keywords_contains_three(self):
        self.assertEqual(len(DEFAULT_KEYWORDS), 3)

    def test_default_keywords_values(self):
        self.assertIn("신도림4차", DEFAULT_KEYWORDS)
        self.assertIn("신도림이편한세상", DEFAULT_KEYWORDS)
        self.assertIn("신도림대장", DEFAULT_KEYWORDS)

    def test_keyword_map_covers_all_defaults(self):
        for kw in DEFAULT_KEYWORDS:
            self.assertIn(kw, KEYWORD_MAP)
            self.assertGreater(len(KEYWORD_MAP[kw]), 0)

    def test_keyword_map_variants(self):
        # 이편한세상은 e편한세상 변형 포함
        variants = KEYWORD_MAP["신도림이편한세상"]
        self.assertTrue(any("이편한세상" in v for v in variants))
        self.assertTrue(any("e편한세상" in v for v in variants))
        # 대장은 공백 포함 변형 포함
        self.assertTrue(any("대장" in v for v in KEYWORD_MAP["신도림대장"]))


class TestMention(unittest.TestCase):
    def test_timestamp_str_seconds_only(self):
        m = Mention(timestamp_sec=45.0, text="신도림 4차 근처", matched_keyword="신도림 4차")
        self.assertEqual(m.timestamp_str, "00:45")

    def test_timestamp_str_minutes(self):
        m = Mention(timestamp_sec=125.0, text="이편한세상 환승", matched_keyword="이편한세상")
        self.assertEqual(m.timestamp_str, "02:05")

    def test_timestamp_str_hours(self):
        m = Mention(timestamp_sec=3661.0, text="신도림 대장 도착", matched_keyword="신도림 대장")
        self.assertEqual(m.timestamp_str, "01:01:01")

    def test_matched_keyword_stored(self):
        m = Mention(timestamp_sec=10.0, text="e편한세상 설명", matched_keyword="e편한세상")
        self.assertEqual(m.matched_keyword, "e편한세상")


class TestVideoResult(unittest.TestCase):
    def setUp(self):
        self.video = VideoResult(
            video_id="abc123",
            title="서울 부동산 투어",
            channel="부동산채널",
            published_at="2024-01-15",
            keyword="신도림4차",
            mentions=[
                Mention(timestamp_sec=60.0, text="신도림 4차에서", matched_keyword="신도림 4차"),
                Mention(timestamp_sec=300.0, text="4차 단지", matched_keyword="4차"),
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


class TestFindKeywordsInTranscript(unittest.TestCase):
    def _make_snippet(self, text, start):
        """v1.x FetchedTranscriptSnippet 객체 모사 (text/start 속성)"""
        snippet = MagicMock()
        snippet.text = text
        snippet.start = start
        return snippet

    @patch("sindorim_search._transcript_api")
    def test_finds_variant_keyword(self, mock_api):
        """'e편한세상' 변형으로도 매칭되는지 확인"""
        mock_api.fetch.return_value = [
            self._make_snippet("오늘은 신도림 e편한세상을 소개합니다", 10.0),
            self._make_snippet("여기는 강남입니다", 45.0),
        ]

        mentions, status = find_keywords_in_transcript("test_id", ["이편한세상", "e편한세상"])
        self.assertEqual(status, "ok")
        self.assertEqual(len(mentions), 1)
        self.assertEqual(mentions[0].matched_keyword, "e편한세상")

    @patch("sindorim_search._transcript_api")
    def test_finds_spaced_keyword(self, mock_api):
        """공백 포함 변형('신도림 4차')으로 매칭되는지 확인"""
        mock_api.fetch.return_value = [
            self._make_snippet("신도림 4차 아파트입니다", 20.0),
        ]

        mentions, status = find_keywords_in_transcript("test_id", ["신도림 4차", "신도림4차", "4차"])
        self.assertEqual(status, "ok")
        self.assertEqual(len(mentions), 1)
        self.assertEqual(mentions[0].matched_keyword, "신도림 4차")

    @patch("sindorim_search._transcript_api")
    def test_no_duplicate_per_entry(self, mock_api):
        """한 문장에 여러 키워드가 있어도 중복 없이 1건만 기록"""
        mock_api.fetch.return_value = [
            self._make_snippet("신도림 4차 신도림4차", 5.0),
        ]

        mentions, status = find_keywords_in_transcript("test_id", ["신도림 4차", "신도림4차"])
        self.assertEqual(len(mentions), 1)

    @patch("sindorim_search._transcript_api")
    def test_no_match_returns_empty(self, mock_api):
        mock_api.fetch.return_value = [
            self._make_snippet("오늘은 강남 아파트를 알아봅니다", 5.0),
        ]

        mentions, status = find_keywords_in_transcript("test_id", ["이편한세상", "e편한세상"])
        self.assertEqual(mentions, [])
        self.assertEqual(status, "ok")

    @patch("sindorim_search._transcript_api")
    def test_blocked_returns_blocked_status(self, mock_api):
        mock_api.fetch.side_effect = Exception("403 Forbidden")
        mock_api.list.side_effect = Exception("403 Forbidden")

        mentions, status = find_keywords_in_transcript("test_id", ["4차", "이편한세상"])
        self.assertEqual(mentions, [])
        self.assertEqual(status, "blocked")

    @patch("sindorim_search._transcript_api")
    def test_no_transcript_returns_status(self, mock_api):
        mock_api.fetch.side_effect = Exception("no transcript available")
        mock_api.list.side_effect = Exception("no transcript available")

        mentions, status = find_keywords_in_transcript("test_id", ["4차"])
        self.assertEqual(mentions, [])
        self.assertEqual(status, "no_transcript")


class TestSearchKeywordMentions(unittest.TestCase):
    @patch("sindorim_search.find_keywords_in_transcript")
    def test_filters_videos_with_mentions(self, mock_find):
        video_list = [
            {"video_id": "vid1", "title": "서울 부동산", "channel": "채널A", "published_at": "2024-01-01"},
            {"video_id": "vid2", "title": "부산 여행",   "channel": "채널B", "published_at": "2024-02-01"},
            {"video_id": "vid3", "title": "신도림 4차 완전정복", "channel": "채널C", "published_at": "2024-03-01"},
        ]

        def side_effect(video_id, keywords):
            if video_id == "vid1":
                return [Mention(30.0, "신도림 4차 지나쳐", "신도림 4차")], "ok"
            if video_id == "vid3":
                return [
                    Mention(10.0, "신도림 4차입니다", "신도림 4차"),
                    Mention(60.0, "4차 출구", "4차"),
                ], "ok"
            return [], "no_transcript"

        mock_find.side_effect = side_effect
        results, stats = search_keyword_mentions(
            video_list, "신도림4차", ["신도림 4차", "신도림4차", "4차"], delay=0
        )

        self.assertEqual(len(results), 2)
        self.assertEqual(results[0].video_id, "vid1")
        self.assertEqual(results[1].video_id, "vid3")
        self.assertEqual(len(results[1].mentions), 2)
        self.assertTrue(all(r.keyword == "신도림4차" for r in results))
        self.assertEqual(stats["ok"], 2)
        self.assertEqual(stats["no_transcript"], 1)

    @patch("sindorim_search.find_keywords_in_transcript")
    def test_each_keyword_tagged_correctly(self, mock_find):
        video_list = [
            {"video_id": "vid1", "title": "부동산 영상", "channel": "채널A", "published_at": "2024-01-01"}
        ]
        for query_kw, variants in KEYWORD_MAP.items():
            mock_find.return_value = [Mention(10.0, f"{variants[0]} 언급", variants[0])], "ok"
            results, stats = search_keyword_mentions(video_list, query_kw, variants, delay=0)
            self.assertEqual(len(results), 1)
            self.assertEqual(results[0].keyword, query_kw)
            self.assertEqual(stats["ok"], 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
