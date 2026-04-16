"""
신도림 단지 YouTube 언급 검색기

YouTube 영상의 자막/트랜스크립트에서 지정 키워드가 나오는
영상과 해당 타임스탬프를 검색합니다.

YouTube 검색어(query)와 트랜스크립트 검색어(transcript_keyword)를 분리해서
- YouTube 검색: "신도림4차" 등 아파트 단지명으로 관련 영상 수집
- 트랜스크립트: 자막에서 실제로 언급되는 단어("4차", "이편한세상" 등)로 매칭

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

import requests
from dotenv import load_dotenv
from youtube_transcript_api import YouTubeTranscriptApi

load_dotenv()

# 브라우저처럼 보이는 세션 (GitHub Actions 환경의 403 차단 우회)
def _make_http_session() -> requests.Session:
    session = requests.Session()
    session.headers.update({
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
    })
    return session

_transcript_api = YouTubeTranscriptApi(http_client=_make_http_session())

# YouTube 검색어  →  트랜스크립트에서 찾을 키워드 목록 (공백·표기 변형 대응)
KEYWORD_MAP: dict[str, list[str]] = {
    "신도림4차":      ["신도림 4차", "신도림4차", "4차"],
    "신도림이편한세상": ["이편한세상", "e편한세상", "신도림 e편한세상", "신도림이편한세상"],
    "신도림대장":     ["신도림 대장", "신도림대장", "대장아파트", "구로 대장"],
}
DEFAULT_KEYWORDS = list(KEYWORD_MAP.keys())

YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY", "")
TRANSCRIPT_LANGUAGES = ["ko", "ko-KR", "en"]  # 한국어 우선, 영어 fallback


@dataclass
class Mention:
    """영상 내 키워드 언급 정보"""

    timestamp_sec: float
    text: str
    matched_keyword: str  # 실제로 매칭된 트랜스크립트 키워드

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
    keyword: str           # YouTube 검색어 (단지명)
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


def find_keywords_in_transcript(video_id: str, keywords: list[str]) -> tuple[list[Mention], str]:
    """영상 트랜스크립트에서 키워드 목록 중 하나라도 나오는 타임스탬프 반환.

    Returns:
        (mentions, status)  status: "ok" | "no_transcript" | "blocked" | "error"
    """
    try:
        # v1.x API: 한국어 우선, 없으면 영어, 없으면 첫 번째 자막 사용
        try:
            fetched = _transcript_api.fetch(video_id, languages=TRANSCRIPT_LANGUAGES)
        except Exception:
            # 지정 언어 없으면 전체 목록에서 첫 번째 자막으로 재시도
            tl = _transcript_api.list(video_id)
            transcript_obj = next(iter(tl), None)
            if transcript_obj is None:
                return [], "no_transcript"
            fetched = transcript_obj.fetch()

        mentions = []
        for entry in fetched:
            # v1.x: FetchedTranscriptSnippet 객체 (.text, .start 속성)
            text = entry.text if hasattr(entry, "text") else entry.get("text", "")
            start = entry.start if hasattr(entry, "start") else entry.get("start", 0)
            for kw in keywords:
                if kw in text:
                    mentions.append(
                        Mention(
                            timestamp_sec=start,
                            text=text.strip(),
                            matched_keyword=kw,
                        )
                    )
                    break  # 한 문장에 여러 키워드 중복 방지
        return mentions, "ok"

    except Exception as e:
        err = str(e).lower()
        if "403" in err or "forbidden" in err:
            return [], "blocked"
        if "disabled" in err or "no transcript" in err or "could not retrieve" in err:
            return [], "no_transcript"
        return [], "error"


def search_keyword_mentions(
    video_list: list[dict],
    query_keyword: str,
    transcript_keywords: list[str],
    delay: float = 0.5,
) -> list[VideoResult]:
    """영상 목록에서 트랜스크립트 키워드 언급을 검색하고 결과 반환"""
    results = []
    total = len(video_list)
    stats = {"ok": 0, "no_transcript": 0, "blocked": 0, "error": 0}

    for idx, video in enumerate(video_list, 1):
        video_id = video["video_id"]
        title = video["title"]
        print(f"  [{idx:3d}/{total}] {title[:50]}", end="", flush=True)

        mentions, status = find_keywords_in_transcript(video_id, transcript_keywords)
        stats[status] = stats.get(status, 0) + 1

        if mentions:
            result = VideoResult(
                video_id=video_id,
                title=title,
                channel=video["channel"],
                published_at=video["published_at"],
                keyword=query_keyword,
                mentions=mentions,
            )
            results.append(result)
            print(f" → {len(mentions)}회 언급")
        else:
            label = {"no_transcript": "자막없음", "blocked": "차단됨", "error": "오류"}.get(status, "없음")
            print(f" → {label}")

        if delay > 0 and idx < total:
            time.sleep(delay)

    print(f"\n  [트랜스크립트 통계] 성공:{stats['ok']} 자막없음:{stats['no_transcript']} 차단:{stats['blocked']} 오류:{stats['error']}")
    return results


def print_results(
    query_keyword: str,
    video_list: list[dict],
    mention_results: list[VideoResult],
) -> None:
    """단일 키워드의 YouTube 검색 영상 목록 + 트랜스크립트 언급 결과 출력"""
    print(f"\n  [ YouTube 검색 영상 목록: '{query_keyword}' ({len(video_list)}개) ]")
    for i, v in enumerate(video_list, 1):
        vid_url = f"https://www.youtube.com/watch?v={v['video_id']}"
        print(f"  {i:2d}. {v['title']}")
        print(f"      {vid_url}")

    if mention_results:
        print(f"\n  [ 트랜스크립트 언급 영상: {len(mention_results)}개 ]")
        for video in mention_results:
            print(f"\n  ▶ {video.title}")
            print(f"    채널: {video.channel}  |  날짜: {video.published_at}")
            print(f"    영상: {video.video_url}")
            for mention in video.mentions:
                print(f"    {mention.timestamp_str} ({mention.matched_keyword}): {video.mention_url(mention)}")
                print(f"           \"{mention.text}\"")
    else:
        print(f"\n  → 트랜스크립트에서 언급 없음\n")


def run_keyword_search(
    youtube,
    query_keyword: str,
    transcript_keywords: list[str],
    max_results: int,
    delay: float,
    channel_id: str | None = None,
    video_ids_raw: str | None = None,
) -> tuple[list[dict], list[VideoResult]]:
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
        video_list = search_videos(youtube, query_keyword, max_results)

    if not video_list:
        print(f"  검색된 영상 없음\n")
        return [], []

    print(f"  총 {len(video_list)}개 영상 트랜스크립트 분석 중...\n")
    mention_results = search_keyword_mentions(
        video_list, query_keyword, transcript_keywords, delay
    )
    return video_list, mention_results


def parse_args():
    parser = argparse.ArgumentParser(
        description="YouTube 영상에서 신도림 단지 언급 타임스탬프 검색",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=f"""
기본 검색 키워드: {', '.join(DEFAULT_KEYWORDS)}

예시:
  # 기본 키워드 3개 자동 검색
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

    all_mention_results: list[VideoResult] = []

    for query_keyword in keywords:
        transcript_keywords = KEYWORD_MAP.get(query_keyword, [query_keyword])

        print(f"[키워드: {query_keyword}]")
        print(f"  트랜스크립트 검색어: {', '.join(transcript_keywords)}")
        print(f"{'-' * 50}")

        video_list, mention_results = run_keyword_search(
            youtube=youtube,
            query_keyword=query_keyword,
            transcript_keywords=transcript_keywords,
            max_results=args.max_results,
            delay=args.delay,
            channel_id=args.channel_id,
            video_ids_raw=args.video_ids,
        )
        print_results(query_keyword, video_list, mention_results)
        all_mention_results.extend(mention_results)

    # 전체 요약
    print(f"\n{'=' * 70}")
    print(f"검색 완료 | 키워드 {len(keywords)}개 | 트랜스크립트 언급 영상 {len(all_mention_results)}개")
    for kw in keywords:
        count = sum(1 for r in all_mention_results if r.keyword == kw)
        print(f"  - {kw}: {count}개 영상")
    print(f"{'=' * 70}\n")


if __name__ == "__main__":
    main()
