"""
서울 공공서비스 예약 - 난지캠핑장 일반캠핑존 4인용 토요일 잔여 확인기

목록 페이지에서 동적으로 서비스를 찾아 달력의 신청수/총모집수를 파싱합니다.
"""
import logging
import os
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import List, Optional, Tuple

from playwright.async_api import BrowserContext, Page, async_playwright

logger = logging.getLogger(__name__)

# 캠핑장 목록 검색 페이지 (하드코딩된 서비스 ID 불필요)
LIST_PAGE_URL = (
    "https://yeyak.seoul.go.kr/web/search/"
    "selectPageListDetailSearchImg.do?code=T500&dCode=T502"
)
BASE_URL = "https://yeyak.seoul.go.kr"

# 목록에서 매칭할 키워드 (AND 조건)
FILTER_KEYWORDS = ["난지캠핑장", "일반캠핑존", "4인용"]


@dataclass
class AvailableSlot:
    date: date
    title: str      # 서비스 제목 (예: "5월 일반캠핑존 C형(4인용, 데크형) …")
    applied: int    # 신청수
    total: int      # 총모집수
    url: str

    @property
    def remaining(self) -> int:
        return self.total - self.applied

    def __str__(self) -> str:
        weekdays = ["월", "화", "수", "목", "금", "토", "일"]
        wd = weekdays[self.date.weekday()]
        return (
            f"{self.date.year}년 {self.date.month}월 {self.date.day}일 ({wd}) "
            f"[{self.applied}/{self.total}, 잔여 {self.remaining}자리] "
            f"- {self.title}"
        )


def get_upcoming_saturdays(weeks: int = 8) -> List[date]:
    today = date.today()
    return [
        today + timedelta(days=i)
        for i in range(1, weeks * 7 + 1)
        if (today + timedelta(days=i)).weekday() == 5  # 5 = 토요일
    ]


async def check_camping_availability() -> List[AvailableSlot]:
    """
    1. 목록 페이지에서 난지캠핑장 일반캠핑존 4인용 서비스 URL 수집
    2. 각 서비스 페이지 달력에서 토요일 신청수/총모집수 파싱
    3. 잔여 있는 토요일 슬롯 반환
    """
    weeks = int(os.getenv("LOOK_AHEAD_WEEKS", "8"))
    saturdays = set(get_upcoming_saturdays(weeks))
    available_slots: List[AvailableSlot] = []

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage"],
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
        await context.add_init_script(
            "Object.defineProperty(navigator,'webdriver',{get:()=>undefined})"
        )

        try:
            # ── 1단계: 목록 페이지에서 서비스 링크 수집 ──────────
            list_page = await context.new_page()
            services = await _find_service_links(list_page, LIST_PAGE_URL)
            await list_page.close()

            if not services:
                logger.warning(
                    "조건에 맞는 서비스 없음 (키워드: %s)", " + ".join(FILTER_KEYWORDS)
                )
                return []

            logger.info("%d개 서비스 발견", len(services))
            for t, _ in services:
                logger.info("  · %s", t)

            # ── 2단계: 각 서비스 페이지 달력 파싱 ─────────────────
            for title, url in services:
                svc_page = await context.new_page()
                slots = await _check_service_saturdays(svc_page, url, title, saturdays)
                available_slots.extend(slots)
                await svc_page.close()

        except Exception as exc:
            logger.error("가용성 확인 중 오류: %s", exc, exc_info=True)
        finally:
            await browser.close()

    return available_slots


# ─── 목록 페이지 파싱 ────────────────────────────────────────

async def _find_service_links(page: Page, list_url: str) -> List[Tuple[str, str]]:
    """
    목록 페이지에서 FILTER_KEYWORDS 를 모두 포함하는 서비스의 (제목, URL) 반환.
    페이지를 끝까지 스크롤하여 동적 로딩된 항목도 포함합니다.
    """
    logger.info("목록 페이지 로딩: %s", list_url)
    await page.goto(list_url, wait_until="domcontentloaded", timeout=30_000)
    await page.wait_for_timeout(2_000)

    # 페이지 하단까지 스크롤 (lazy load 대응)
    await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
    await page.wait_for_timeout(1_000)

    raw_links: List[dict] = await page.evaluate(
        """
        () => {
            const seen = new Set();
            const results = [];

            // selectReservView.do 를 포함하는 모든 앵커 탐색
            document.querySelectorAll('a[href*="selectReservView"]').forEach(a => {
                const href = a.href;
                if (seen.has(href)) return;

                // 제목: 앵커 자신 또는 가장 가까운 제목 요소
                const titleElem =
                    a.querySelector('h2,h3,h4,strong,.tit,.title,.name') ||
                    a.closest('li,article,.item,.list_item')
                        ?.querySelector('h2,h3,h4,strong,.tit,.title,.name') ||
                    a;

                const title = (titleElem.innerText || titleElem.textContent || '')
                    .trim().replace(/\\s+/g, ' ');

                seen.add(href);
                results.push({ title, href });
            });
            return results;
        }
        """
    )

    matched: List[Tuple[str, str]] = []
    for item in raw_links:
        title: str = item["title"]
        url: str = item["href"]
        if all(kw in title for kw in FILTER_KEYWORDS):
            matched.append((title, url))
            logger.info("서비스 매칭: %s", title)

    return matched


# ─── 서비스 페이지 달력 파싱 ─────────────────────────────────

async def _check_service_saturdays(
    page: Page,
    url: str,
    title: str,
    saturdays: set,
) -> List[AvailableSlot]:
    """
    서비스 예약 페이지 달력에서 토요일 셀을 파싱하여 잔여 있는 날짜 반환.

    달력 셀 형식 (스크린샷 기준):
      줄1: 날짜 숫자 (예: "2")
      줄2: 신청수/총모집수 (예: "13/13" or "6/13")
    """
    logger.info("예약 페이지 로딩: %s", url)
    await page.goto(url, wait_until="domcontentloaded", timeout=30_000)
    await page.wait_for_timeout(2_000)

    # 현재 달력이 보여주는 년/월 파악
    current_ym = await _get_calendar_year_month(page)
    if not current_ym:
        current_ym = (date.today().year, date.today().month)

    found: List[AvailableSlot] = []
    months_needed = sorted({(s.year, s.month) for s in saturdays})

    for year, month in months_needed:
        # 필요한 달까지 이동
        nav_count = 0
        while current_ym < (year, month) and nav_count < 12:
            if not await _click_next_month(page):
                logger.warning("다음달 버튼을 찾지 못했습니다 (현재: %s-%02d)", *current_ym)
                break
            await page.wait_for_timeout(800)
            y, m = current_ym
            current_ym = (y + (m // 12), m % 12 + 1)
            nav_count += 1

        if current_ym != (year, month):
            continue

        # 달력 셀 파싱
        cells = await _parse_calendar_cells(page, year, month)
        for cell_date, applied, total in cells:
            if cell_date not in saturdays:
                continue
            if applied < total:
                found.append(
                    AvailableSlot(
                        date=cell_date,
                        title=title,
                        applied=applied,
                        total=total,
                        url=url,
                    )
                )
                logger.info(
                    "가용 토요일 발견: %s [%d/%d, 잔여 %d]",
                    cell_date, applied, total, total - applied,
                )
            else:
                logger.debug("만석: %s [%d/%d]", cell_date, applied, total)

    return found


async def _parse_calendar_cells(
    page: Page, year: int, month: int
) -> List[Tuple[date, int, int]]:
    """
    달력 테이블에서 (날짜, 신청수, 총모집수) 추출.
    날짜의 요일은 date 객체로 직접 계산하므로 DOM 열 위치에 의존하지 않습니다.
    """
    raw: List[dict] = await page.evaluate(
        """
        () => {
            const results = [];
            // 달력 테이블 선택 (다양한 클래스명 대응)
            const table =
                document.querySelector('table.cal') ||
                document.querySelector('table.calendar') ||
                document.querySelector('[class*="cal"] table') ||
                document.querySelector('.wrap_cal table') ||
                document.querySelector('table');

            if (!table) return results;

            table.querySelectorAll('tbody tr').forEach(tr => {
                tr.querySelectorAll('td').forEach(td => {
                    const raw = (td.innerText || '').trim();
                    if (!raw) return;

                    // 날짜 숫자 (첫 번째 숫자 토큰)
                    const dayMatch = raw.match(/^(\\d{1,2})/);
                    if (!dayMatch) return;
                    const day = parseInt(dayMatch[1], 10);
                    if (day < 1 || day > 31) return;

                    // 신청수/총모집수 (예: "13/13", "6/13")
                    const ratioMatch = raw.match(/(\\d+)\\s*\\/\\s*(\\d+)/);
                    if (!ratioMatch) return;

                    results.push({
                        day,
                        applied: parseInt(ratioMatch[1], 10),
                        total:   parseInt(ratioMatch[2], 10),
                    });
                });
            });
            return results;
        }
        """
    )

    result: List[Tuple[date, int, int]] = []
    for cell in raw:
        try:
            d = date(year, month, cell["day"])
        except ValueError:
            continue
        result.append((d, cell["applied"], cell["total"]))
    return result


async def _get_calendar_year_month(page: Page) -> Optional[Tuple[int, int]]:
    """달력 헤더에서 현재 년/월 파악 (예: "2026년 05월" → (2026, 5))"""
    try:
        text: str = await page.evaluate(
            """
            () => {
                const el =
                    document.querySelector('.cal_title, .calendar_title, '
                                          + '.yyyymm, [class*="cal_tit"], '
                                          + '.cal h2, .cal h3, .wrap_cal strong');
                return el ? el.innerText.trim() : '';
            }
            """
        )
        m = re.search(r"(\d{4})[년\s]+(\d{1,2})[월]?", text)
        if m:
            return int(m.group(1)), int(m.group(2))
    except Exception:
        pass
    return None


async def _click_next_month(page: Page) -> bool:
    """다음달 버튼 클릭, 성공 시 True"""
    selectors = [
        ".cal_next", "button.next", "a.next",
        ".btn_next", "[class*='next_month']",
        "[title='다음달']", "[title='다음']",
        "[aria-label='다음달']", "[aria-label='next month']",
        "button[class*='next']", "a[class*='next']",
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
