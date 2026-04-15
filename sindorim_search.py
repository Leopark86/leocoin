"""
신도림 단지 YouTube 언급 검색기

YouTube 영상의 자막/트랜스크립트에서 지정 키워드가 나오는
영상과 해당 타임스탬프를 검색합니다.

기본 키워드: 신도림4차, 신도림이편한세상, 신도림대장

사용법:
    # 기본 키워드 3개로 자동 검색 (GitHub Actions 기본 모드)
    python sindorim_search.py

    # 키워드 직접 지정
    python sindorim_search.py --keywords "신도림4차,신도림이편한세상"

    # 특정 채널 전체 영상에서 검색
    python sindorim_search.py --channel-id UCxxxxxxxx

    # 특정 영상 ID 목록에서 검색
    python sindorim_search.py --video-ids "id1,id2,id3"
"""

import argparse
import os
import sys
import time
from dataclasses import dataclass, field
from datetime import timedelta

from dotenv import load_dotenv
from youtube_transcript_api import (
    NoTranscriptFound,
    TranscriptsDisabled,
    YouTubeTranscriptApi,
)
from youtube_transcript_api._errors import VideoUnavailable

load_dotenv()

# 기본 검색 키워드 목록
DEFAULT_KEYWORDS = ["신도림4차", "신도림이편한세상", "신도림대장"]

YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY", "")
TRANSCRIPT_LANGUAGES = ["ko", "ko-KR", "en"]  # 한국어 우선, 영어 fallback


@dataclass
class Mention:
    """영상 내 키워드 언급 정보"""

    timestamp_sec: float
    text: str

    @property
    def timestamp_str(self) -> str:
        td = timedelta(seconds=int(self.timestamp_sec))
        total_seconds = int(td.total_seconds())
        hours = total_seconds // 3600
        minutes = (total_seconds % 3600) // 60
        seconds = total_seconds % 60
        if hours > 0:
            return f"{hours:02d}:{minutes:02d}:{seconds:02d}"
        return f"{minutes:02d}:{seconds:02d}"

    @property
    def youtube_url_timestamp(self) -> str:
        return f"?t={int(self.timestamp_sec)}s"


@dataclass
class VideoResult:
    """영상 검색 결과"""

    video_id: str
    title: str
    channel: str
    published_at: str
    keyword: str
    mentions: list[Mention] = field(default_factory=list)

    @property
    def video_url(self) -> str:
        return f"https://www.youtube.com/watch?v={self.video_id}"

    def mention_url(self, mention: Mention) -> str:
        return f"https://www.youtube.com/watch?v={self.video_id}&t={int(mention.timestamp_sec)}s"


def build_youtube_client():
    """YouTube Data API 클라이언트 생성"""
    if not YOUTUBE_API_KEY:
        raise ValueError(
            "YOUTUBE_API_KEY 환경변수가 설정되지 않았습니다.\n"
            ".env 파일에 YOUTUBE_API_KEY=<your_key> 를 추가하세요."
        )
    try:
        from googleapiclient.discovery import build as yt_build
    except ImportError as e:
        raise ImportError(
            f"google-api-python-client 패키지가 필요합니다: pip install google-api-python-client\n원인: {e}"
        ) from e
    return yt_build("youtube", "v3", developerKey=YOUTUBE_API_KEY)


def search_videos(youtube, query: str, max_results: int = 50) -> list[dict]:
    """YouTube 검색 API로 영상 목록 조회"""
    videos = []
    next_page_token = None

    while len(videos) < max_results:
        batch = min(50, max_results - len(videos))
        try:
            response = (
                youtube.search()
                .list(
                    part="snippet",
                    q=query,
                    type="video",
                    maxResults=batch,
                    pageToken=next_page_token,
                )
                .execute()
            )
        except Exception as e:
            print(f"[오류] YouTube API 검색 실패: {e}", file=sys.stderr)
            break

        for item in response.get("items", []):
            snippet = item["snippet"]
            videos.append(
                {
                    "video_id": item["id"]["videoId"],
                    "title": snippet["title"],
                    "channel": snippet["channelTitle"],
                    "published_at": snippet["publishedAt"][:10],
                }
            )

        next_page_token = response.get("nextPageToken")
        if not next_page_token:
            break

    return videos


def get_channel_videos(youtube, channel_id: str, max_results: int = 200) -> list[dict]:
    """채널의 전체 영상 목록 조회"""
    try:
        channel_resp = (
            youtube.channels()
            .list(part="contentDetails,snippet", id=channel_id)
            .execute()
        )
    except Exception as e:
        print(f"[오류] 채널 정보 조회 실패: {e}", file=sys.stderr)
        return []

    items = channel_resp.get("items", [])
    if not items:
        print(f"[오류] 채널 ID '{channel_id}'를 찾을 수 없습니다.", file=sys.stderr)
        return []

    uploads_playlist_id = items[0]["contentDetails"]["relatedPlaylists"]["uploads"]
    channel_name = items[0]["snippet"]["title"]
    print(f"채널 '{channel_name}' 의 업로드 영상을 불러오는 중...")

    videos = []
    next_page_token = None

    while len(videos) < max_results:
        batch = min(50, max_results - len(videos))
        try:
            playlist_resp = (
                youtube.playlistItems()
                .list(
                    part="snippet",
                    playlistId=uploads_playlist_id,
                    maxResults=batch,
                    pageToken=next_page_token,
                )
                .execute()
            )
        except Exception as e:
            print(f"[오류] 재생목록 조회 실패: {e}", file=sys.stderr)
            break

        for item in playlist_resp.get("items", []):
            snippet = item["snippet"]
            video_id = snippet["resourceId"]["videoId"]
            videos.append(
                {
                    "video_id": video_id,
                    "title": snippet["title"],
                    "channel": channel_name,
                    "published_at": snippet["publishedAt"][:10],
                }
            )

        next_page_token = playlist_resp.get("nextPageToken")
        if not next_page_token:
            break

    return videos


def get_video_info(youtube, video_ids: list[str]) -> list[dict]:
    """영상 ID 목록으로 영상 정보 조회"""
    videos = []
    for i in range(0, len(video_ids), 50):
        batch_ids = video_ids[i : i + 50]
        try:
            response = (
                youtube.videos()
                .list(part="snippet", id=",".join(batch_ids))
                .execute()
            )
        except Exception as e:
            print(f"[오류] 영상 정보 조회 실패: {e}", file=sys.stderr)
            continue

        for item in response.get("items", []):
            snippet = item["snippet"]
            videos.append(
                {
                    "video_id": item["id"],
                    "title": snippet["title"],
                    "channel": snippet["channelTitle"],
                    "published_at": snippet["publishedAt"][:10],
                }
            )
    return videos


def find_keyword_in_transcript(video_id: str, keyword: str) -> list[Mention]:
    """영상 트랜스크립트에서 키워드가 나오는 타임스탬프 목록 반환"""
    try:
        transcript_list = YouTubeTranscriptApi.list_transcripts(video_id)

        # 한국어 자막 우선 탐색
        transcript = None
        for lang in TRANSCRIPT_LANGUAGES:
            try:
                transcript = transcript_list.find_transcript([lang])
                break
            except NoTranscriptFound:
                continue

        # 자동 생성 자막 시도
        if transcript is None:
            try:
                transcript = transcript_list.find_generated_transcript(
                    TRANSCRIPT_LANGUAGES
                )
            except NoTranscriptFound:
                all_transcripts = list(transcript_list)
                if all_transcripts:
                    transcript = all_transcripts[0]
                else:
                    return []

        entries = transcript.fetch()
        mentions = []
        for entry in entries:
            text = entry.get("text", "")
            if keyword in text:
                mentions.append(
                    Mention(
                        timestamp_sec=entry["start"],
                        text=text.strip(),
                    )
                )
        return mentions

    except TranscriptsDisabled:
        return []
    except VideoUnavailable:
        return []
    except Exception:
        return []


def search_keyword_mentions(
    video_list: list[dict],
    keyword: str,
    delay: float = 0.5,
) -> list[VideoResult]:
    """영상 목록에서 단일 키워드 언급을 검색하고 결과 반환"""
    results = []
    total = len(video_list)

    for idx, video in enumerate(video_list, 1):
        video_id = video["video_id"]
        title = video["title"]
        print(f"  [{idx:3d}/{total}] {title[:50]}", end="", flush=True)

        mentions = find_keyword_in_transcript(video_id, keyword)

        if mentions:
            result = VideoResult(
                video_id=video_id,
                title=title,
                channel=video["channel"],
                published_at=video["published_at"],
                keyword=keyword,
                mentions=mentions,
            )
            results.append(result)
            print(f" → {len(mentions)}회 언급")
        else:
            print(" → 없음")

        if delay > 0 and idx < total:
            time.sleep(delay)

    return results


def print_results(results: list[VideoResult], keyword: str) -> None:
    """단일 키워드 검색 결과 출력"""
    if not results:
        print(f"  '{keyword}' 언급 없음\n")
        return

    print(f"  '{keyword}' 언급 영상: {len(results)}개\n")
    for i, video in enumerate(results, 1):
        print(f"  [{i}] {video.title}")
        print(f"      채널: {video.channel}  |  날짜: {video.published_at}")
        print(f"      URL: {video.video_url}")
        print(f"      언급 {len(video.mentions)}회:")
        for mention in video.mentions:
            print(f"        {mention.timestamp_str}  →  {video.mention_url(mention)}")
            print(f"                \"{mention.text}\"")
        print()


def run_keyword_search(
    youtube,
    keyword: str,
    max_results: int,
    delay: float,
    channel_id: str | None = None,
    video_ids_raw: str | None = None,
) -> list[VideoResult]:
    """키워드 하나에 대해 영상 수집 → 트랜스크립트 검색 전체 파이프라인 실행"""
    video_list = []

    if channel_id:
        video_list = get_channel_videos(youtube, channel_id, max_results)
    elif video_ids_raw:
        ids = [v.strip() for v in video_ids_raw.split(",") if v.strip()]
        if youtube:
            video_list = get_video_info(youtube, ids)
        else:
            video_list = [
                {
                    "video_id": v,
                    "title": f"영상 {v}",
                    "channel": "알 수 없음",
                    "published_at": "알 수 없음",
                }
                for v in ids
            ]
    else:
        # 기본 모드: 키워드 자체를 YouTube 검색어로 사용
        video_list = search_videos(youtube, keyword, max_results)

    if not video_list:
        print(f"  검색된 영상 없음\n")
        return []

    print(f"  총 {len(video_list)}개 영상 트랜스크립트 분석 중...\n")
    return search_keyword_mentions(video_list, keyword, delay)


def parse_args():
    parser = argparse.ArgumentParser(
        description="YouTube 영상에서 신도림 단지 언급 타임스탬프 검색",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=f"""
기본 검색 키워드: {', '.join(DEFAULT_KEYWORDS)}

예시:
  # 기본 키워드 3개 자동 검색 (YouTube 검색 → 트랜스크립트 분석)
  python sindorim_search.py

  # 키워드 직접 지정
  python sindorim_search.py --keywords "신도림4차,신도림대장"

  # 특정 채널 전체 영상에서 키워드 검색
  python sindorim_search.py --channel-id UCxxxxxxxxxxxxxxxxxx

  # 특정 영상 ID 목록에서 검색
  python sindorim_search.py --video-ids "dQw4w9WgXcQ,abc123def456"
        """,
    )

    parser.add_argument(
        "--keywords",
        type=str,
        default=",".join(DEFAULT_KEYWORDS),
        help=f"쉼표로 구분된 검색 키워드 목록 (기본값: {','.join(DEFAULT_KEYWORDS)})",
    )
    parser.add_argument(
        "--channel-id", "-c", type=str, default=None,
        help="YouTube 채널 ID (채널 전체 영상 분석)",
    )
    parser.add_argument(
        "--video-ids", "-v", type=str, default=None,
        help="쉼표로 구분된 YouTube 영상 ID 목록",
    )
    parser.add_argument(
        "--max-results", "-n", type=int, default=50,
        help="키워드당 최대 검색 영상 수 (기본값: 50)",
    )
    parser.add_argument(
        "--delay", type=float, default=0.5,
        help="API 요청 간 대기 시간(초) (기본값: 0.5)",
    )

    return parser.parse_args()


def main():
    args = parse_args()
    keywords = [k.strip() for k in args.keywords.split(",") if k.strip()]

    print(f"\n유튜브 신도림 단지 언급 검색기")
    print(f"{'=' * 70}")
    print(f"검색 키워드: {', '.join(keywords)}")
    print(f"{'=' * 70}\n")

    try:
        youtube = build_youtube_client()
    except ValueError as e:
        if args.video_ids:
            print(f"[경고] {e}\n영상 메타데이터 없이 트랜스크립트만 검색합니다.\n")
            youtube = None
        else:
            print(f"[오류] {e}", file=sys.stderr)
            sys.exit(1)

    all_results: list[VideoResult] = []

    for keyword in keywords:
        print(f"[키워드: {keyword}]")
        print(f"{'-' * 50}")
        results = run_keyword_search(
            youtube=youtube,
            keyword=keyword,
            max_results=args.max_results,
            delay=args.delay,
            channel_id=args.channel_id,
            video_ids_raw=args.video_ids,
        )
        print_results(results, keyword)
        all_results.extend(results)

    # 전체 요약 + URL 목록
    print(f"{'=' * 70}")
    print(f"검색 완료 | 키워드 {len(keywords)}개 | 총 언급 영상 {len(all_results)}개")
    for kw in keywords:
        count = sum(1 for r in all_results if r.keyword == kw)
        print(f"  - {kw}: {count}개 영상")

    if all_results:
        print(f"\n{'=' * 70}")
        print("[ 언급 영상 URL 전체 목록 ]")
        print(f"{'=' * 70}")
        for kw in keywords:
            kw_results = [r for r in all_results if r.keyword == kw]
            if not kw_results:
                continue
            print(f"\n▶ {kw} ({len(kw_results)}개)")
            for video in kw_results:
                print(f"  제목  : {video.title}")
                print(f"  채널  : {video.channel}  |  날짜: {video.published_at}")
                print(f"  영상  : {video.video_url}")
                for mention in video.mentions:
                    print(f"  {mention.timestamp_str} : {video.mention_url(mention)}")
                print()

    print(f"{'=' * 70}\n")


if __name__ == "__main__":
    main()
