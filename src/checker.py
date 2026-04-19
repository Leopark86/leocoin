"""
서울 공공서비스 예약 - 난지캠핑장 일반캠핑존 4인용 토요일 잔여 확인기

yeyak.seoul.go.kr 에서 Playwright로 브라우저를 에뮬레이션하여
AJAX API 응답을 가로채고 DOM을 파싱해 잔여 여부를 확인합니다.
"""
import asyncio
import json
import logging
import os
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import List, Optional

from playwright.async_api import (
    Browser,
    BrowserContext,
    Page,
    Response,
    async_playwright,
)

logger = logging.getLogger(__name__)

# ─── 서비스 설정 ────────────────────────────────────────────
BASE_URL = "https://yeyak.seoul.go.kr"

# 2026 한강공원 난지캠핑장 (시즌마다 갱신 필요)
RSV_SVC_ID = os.getenv("RSV_SVC_ID", "S260331091154779264")
SERVICE_URL = f"{BASE_URL}/web/reservation/selectReservView.do?rsv_svc_id={RSV_SVC_ID}"

TARGET_ZONE = "일반캠핑존"
TARGET_CAPACITY = "4인용"

# AJAX 엔드포인트 키워드 (가로채기용)
AJAX_KEYWORDS = ["Calendar", "calendar", "posbl", "Posbl", "avail", "Avail", "Rsv", "rsv"]

# 달력에서 예약 가능 날짜로 인식하는 CSS 클래스 패턴 목록
AVAILABLE_CELL_SELECTORS = [
    "td.possible",
    "td.possible_date",
    "td[class*='possible']",
    "td.avail",
    "td.available",
    "td[class*='avail']",
    "td.on:not(.end):not(.full):not(.close)",
    "td.active",
    "td[class*='able']:not([class*='dis'])",
    # 비활성화 클래스가 없는 날짜 셀 (마지막 수단)
    "td.num:not(.end):not(.close):not(.full):not(.disable):not(.disabled):not(.no)",
]

NEXT_MONTH_SELECTORS = [
    "button.next",
    "a.next",
    ".btn_next",
    ".next_month",
    "button[class*='next']",
    "a[class*='next']",
    "button[title='다음달']",
    "a[title='다음달']",
    "button[title='다음']",
    "[aria-label='다음달']",
    "[aria-label='next month']",
]


@dataclass
class AvailableSlot:
    date: date
    zone: str
    capacity: str
    url: str

    def __str__(self) -> str:
        weekdays = ["월", "화", "수", "목", "금", "토", "일"]
        wd = weekdays[self.date.weekday()]
        return (
            f"{self.date.year}년 {self.date.month}월 {self.date.day}일 ({wd}) "
            f"- {self.zone} {self.capacity}"
        )


def get_upcoming_saturdays(weeks: int = 8) -> List[date]:
    """오늘부터 N주 이내 토요일 날짜 목록 반환 (오늘 포함하지 않음)"""
    today = date.today()
    result: List[date] = []
    for i in range(1, weeks * 7 + 1):
        d = today + timedelta(days=i)
        if d.weekday() == 5:  # 5 = 토요일
            result.append(d)
    return result


async def check_camping_availability() -> List[AvailableSlot]:
    """
    난지캠핑장 일반캠핑존 4인용의 토요일 잔여 여부를 확인합니다.

    1단계: Playwright 브라우저로 예약 페이지 로드
    2단계: AJAX API 응답 가로채기 (JSON 파싱)
    3단계: 일반캠핑존 / 4인용 UI 선택
    4단계: API 데이터 또는 DOM 달력에서 가용 토요일 탐색
    """
    available_slots: List[AvailableSlot] = []
    intercepted_api: dict = {}

    async with async_playwright() as p:
        browser: Browser = await p.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-dev-shm-usage",
                "--disable-blink-features=AutomationControlled",
            ],
        )
        context: BrowserContext = await browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/122.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1280, "height": 900},
            locale="ko-KR",
            timezone_id="Asia/Seoul",
        )

        # 자동화 탐지 우회
        await context.add_init_script(
            "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
        )

        page: Page = await context.new_page()

        # ── AJAX 응답 가로채기 ──────────────────────────────
        async def handle_response(response: Response) -> None:
            url = response.url
            if BASE_URL not in url:
                return
            if url == SERVICE_URL:
                return
            if not any(kw in url for kw in AJAX_KEYWORDS):
                return
            try:
                text = await response.text()
                text = text.strip()
                if text.startswith(("{", "[")):
                    intercepted_api[url] = json.loads(text)
                    logger.debug("API 응답 캡처: %s", url)
            except Exception:
                pass

        page.on("response", handle_response)

        try:
            logger.info("예약 페이지 로딩: %s", SERVICE_URL)
            await page.goto(SERVICE_URL, wait_until="domcontentloaded", timeout=30_000)
            await page.wait_for_timeout(3_000)

            # ── 일반캠핑존 선택 ────────────────────────────
            zone_ok = await _click_target(page, TARGET_ZONE)
            if zone_ok:
                logger.info("'%s' 선택 완료", TARGET_ZONE)
                await page.wait_for_timeout(1_500)
            else:
                logger.warning("'%s' 요소를 찾지 못했습니다 (계속 진행)", TARGET_ZONE)

            # ── 4인용 선택 ─────────────────────────────────
            cap_ok = await _click_target(page, TARGET_CAPACITY)
            if cap_ok:
                logger.info("'%s' 선택 완료", TARGET_CAPACITY)
                await page.wait_for_timeout(1_500)
            else:
                logger.warning("'%s' 요소를 찾지 못했습니다 (계속 진행)", TARGET_CAPACITY)

            saturdays = get_upcoming_saturdays(
                weeks=int(os.getenv("LOOK_AHEAD_WEEKS", "8"))
            )
            logger.info("확인 대상 토요일 %d개: %s ~ %s", len(saturdays), saturdays[0], saturdays[-1])

            # ── 1순위: AJAX 데이터 파싱 ────────────────────
            if intercepted_api:
                slots = _parse_api_responses(intercepted_api, saturdays)
                if slots:
                    available_slots.extend(slots)
                    logger.info("API에서 %d개 가용 슬롯 발견", len(slots))

            # ── 2순위: DOM 달력 파싱 ───────────────────────
            if not available_slots:
                logger.info("DOM 달력 파싱 시도 중...")
                slots = await _check_calendar_dom(page, saturdays)
                available_slots.extend(slots)

        except Exception as exc:
            logger.error("가용성 확인 중 오류: %s", exc, exc_info=True)
        finally:
            await browser.close()

    return available_slots


# ─── 헬퍼 함수 ──────────────────────────────────────────────

async def _click_target(page: Page, text: str) -> bool:
    """텍스트로 요소를 찾아 클릭. 성공하면 True 반환."""
    selectors = [
        f"text='{text}'",
        f"text={text}",
        f"[title='{text}']",
        f"label:has-text('{text}')",
        f"a:has-text('{text}')",
        f"li:has-text('{text}')",
        f"button:has-text('{text}')",
        f"span:has-text('{text}')",
        f"td:has-text('{text}')",
        f"option:has-text('{text}')",
        f"[value='{text}']",
    ]
    for sel in selectors:
        try:
            elem = page.locator(sel).first
            if await elem.count() > 0 and await elem.is_visible():
                await elem.click()
                return True
        except Exception:
            continue
    return False


def _parse_api_responses(
    intercepted: dict, saturdays: List[date]
) -> List[AvailableSlot]:
    """
    가로챈 AJAX 응답 JSON에서 예약 가능 토요일 추출.

    서울 공공서비스 예약 API는 보통 아래 형태의 JSON을 반환:
    {"list": [{"rsv_day": "20260418", "posbl_yn": "Y", ...}, ...]}
    또는
    [{"day": "20260418", "avail": "Y"}, ...]
    """
    saturday_dates = {s.strftime("%Y%m%d"): s for s in saturdays}
    found: List[AvailableSlot] = []

    for url, data in intercepted.items():
        # 리스트 형태 정규화
        if isinstance(data, list):
            items = data
        elif isinstance(data, dict):
            items = (
                data.get("list")
                or data.get("data")
                or data.get("result")
                or data.get("items")
                or []
            )
        else:
            continue

        if not isinstance(items, list):
            continue

        for item in items:
            if not isinstance(item, dict):
                continue

            # 날짜 필드 탐색
            raw_date: Optional[str] = None
            for key in ("rsv_day", "day", "date", "rsv_dt", "avail_date", "ymd", "calDt"):
                val = item.get(key)
                if val:
                    raw_date = str(val).replace("-", "")[:8]
                    break

            if not raw_date or raw_date not in saturday_dates:
                continue

            # 가용 여부 필드 탐색
            avail_val = None
            for key in ("posbl_yn", "avail", "available", "status", "canRsv", "yn"):
                avail_val = item.get(key)
                if avail_val is not None:
                    break

            is_available = avail_val in ("Y", "y", 1, "1", True, "available", "open")
            if not is_available:
                continue

            d = saturday_dates[raw_date]
            slot = AvailableSlot(
                date=d,
                zone=TARGET_ZONE,
                capacity=TARGET_CAPACITY,
                url=SERVICE_URL,
            )
            found.append(slot)
            logger.info("가용 토요일 발견 (API): %s", d)

    return found


async def _check_calendar_dom(
    page: Page, saturdays: List[date]
) -> List[AvailableSlot]:
    """
    DOM 달력을 직접 파싱하여 예약 가능 토요일 추출.
    AJAX 데이터를 얻지 못했을 때의 폴백.
    """
    found: List[AvailableSlot] = []
    saturday_set = {s: s for s in saturdays}

    months_needed = sorted({(s.year, s.month) for s in saturdays})
    today = date.today()
    current_ym = (today.year, today.month)

    for year, month in months_needed:
        # 필요한 달로 달력 이동
        target_ym = (year, month)
        nav_attempts = 0
        while current_ym < target_ym and nav_attempts < 12:
            next_btn = await _find_element_by_selectors(page, NEXT_MONTH_SELECTORS)
            if next_btn:
                await next_btn.click()
                await page.wait_for_timeout(1_000)
                m = current_ym[1] % 12 + 1
                y = current_ym[0] + (1 if current_ym[1] == 12 else 0)
                current_ym = (y, m)
            else:
                logger.warning("다음달 버튼을 찾지 못했습니다")
                break
            nav_attempts += 1

        # 현재 달의 가용 날짜 파싱
        available_days = await _extract_available_days(page)
        logger.debug("%d-%02d 가용일: %s", year, month, available_days)

        for day in available_days:
            try:
                d = date(year, month, day)
            except ValueError:
                continue
            if d in saturday_set:
                found.append(
                    AvailableSlot(
                        date=d,
                        zone=TARGET_ZONE,
                        capacity=TARGET_CAPACITY,
                        url=SERVICE_URL,
                    )
                )
                logger.info("가용 토요일 발견 (DOM): %s", d)

    return found


async def _extract_available_days(page: Page) -> List[int]:
    """달력 DOM에서 예약 가능한 날짜 숫자 목록 추출"""
    days: List[int] = []
    for selector in AVAILABLE_CELL_SELECTORS:
        try:
            elems = page.locator(selector)
            count = await elems.count()
            if count == 0:
                continue
            for i in range(count):
                try:
                    text = (await elems.nth(i).inner_text()).strip()
                    day = int(text)
                    if 1 <= day <= 31:
                        days.append(day)
                except (ValueError, Exception):
                    continue
            if days:
                break
        except Exception:
            continue
    return list(set(days))


async def _find_element_by_selectors(page: Page, selectors: List[str]):
    """셀렉터 목록을 순서대로 시도해 첫 번째 보이는 요소 반환"""
    for sel in selectors:
        try:
            elem = page.locator(sel).first
            if await elem.count() > 0 and await elem.is_visible():
                return elem
        except Exception:
            continue
    return None
