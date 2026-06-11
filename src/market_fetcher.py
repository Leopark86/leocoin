"""시장 데이터 수집 모듈 (yfinance + KRX API)"""
import logging
from dataclasses import dataclass
from datetime import date, timedelta
from typing import List, Optional

import requests
import yfinance as yf

logger = logging.getLogger(__name__)

# (Yahoo Finance 티커, 표시명, 단위, 배수)
# 엔/원: JPYKRW=X 는 1엔당 원화 → 100엔 기준으로 ×100
ASSETS: list[tuple[str, str, str, float]] = [
    ("CL=F",     "WTI원유",        "USD/bbl", 1.0),
    ("USDKRW=X", "달러/원",        "원",      1.0),
    ("JPYKRW=X", "엔/원 (100엔)",  "원",      100.0),
    ("^TYX",     "미국채 30년",    "%",       1.0),
    ("^TNX",     "미국채 10년",    "%",       1.0),
    ("BTC-USD",  "비트코인",       "USD",     1.0),
    ("GC=F",     "금",             "USD/oz",  1.0),
    ("^KS11",    "KOSPI",           "pt",      1.0),
    ("^KS200",   "KOSPI200 (현물)", "pt",      1.0),
]


@dataclass
class AssetPrice:
    name: str
    unit: str
    price: Optional[float]
    prev_close: Optional[float]
    multiplier: float = 1.0
    error: Optional[str] = None

    @property
    def display_price(self) -> Optional[float]:
        return None if self.price is None else self.price * self.multiplier

    @property
    def change(self) -> Optional[float]:
        if self.price is None or self.prev_close is None:
            return None
        return (self.price - self.prev_close) * self.multiplier

    @property
    def change_pct(self) -> Optional[float]:
        if self.price is None or self.prev_close is None or self.prev_close == 0:
            return None
        return (self.price - self.prev_close) / self.prev_close * 100


def _fetch_one(ticker_str: str) -> tuple[Optional[float], Optional[float]]:
    """(현재가, 전일종가) 반환. 실패 시 (None, None)."""
    # 1차: fast_info (경량 API)
    try:
        fi = yf.Ticker(ticker_str).fast_info
        price = fi.last_price
        prev = fi.previous_close
        if price is not None and float(price) > 0:
            return float(price), float(prev) if prev is not None else None
    except Exception as e:
        logger.debug("fast_info 실패 (%s): %s", ticker_str, e)

    # 2차: 최근 5일 일봉 다운로드
    try:
        df = yf.download(
            ticker_str, period="5d", interval="1d",
            progress=False, auto_adjust=True,
        )
        if df is not None and not df.empty:
            # yfinance 멀티인덱스 대응
            closes = df["Close"] if "Close" in df.columns else df.iloc[:, 0]
            closes = closes.dropna()
            if len(closes) >= 2:
                return float(closes.iloc[-1]), float(closes.iloc[-2])
            if len(closes) == 1:
                return float(closes.iloc[-1]), None
    except Exception as e:
        logger.debug("download 폴백 실패 (%s): %s", ticker_str, e)

    return None, None


_KRX_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Referer": "https://data.krx.co.kr",
    "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
}


def _fetch_kospi200_futures_krx() -> tuple[Optional[float], Optional[float]]:
    """
    KRX 데이터포털 API로 KOSPI200선물 최근월물 종가 조회.
    장중(09:00~15:45 KST) 데이터만 유효, 야간선물 미지원.
    """
    prices: list[float] = []

    # 최근 5영업일을 커버하기 위해 최대 7일 전까지 역순으로 시도
    for delta in range(7):
        trade_date = (date.today() - timedelta(days=delta)).strftime("%Y%m%d")
        try:
            resp = requests.post(
                "https://data.krx.co.kr/comm/bldAttendant/getJsonData.cmd",
                data={
                    "bld":      "dbms/MDC/STAT/standard/MDCSTAT13001",
                    "locale":   "ko_KR",
                    "trdDd":    trade_date,
                    "mktId":    "F",
                    "prodId":   "F102",
                    "pagePath": "/contents/MDC/MAIN/main/MDCMAIN001.cmd",
                },
                headers=_KRX_HEADERS,
                timeout=10,
            )
            resp.raise_for_status()
            items = resp.json().get("output", [])
            for item in items:
                # 최근월물: 거래대금이 가장 큰 항목
                raw = (
                    item.get("trdPrc")
                    or item.get("clsPrc")
                    or item.get("CLSPRC")
                    or item.get("closPrc")
                )
                if raw:
                    prices.append(float(str(raw).replace(",", "")))
                    break   # 첫 번째 항목(최근월물) 하나만 사용

            if prices:
                if len(prices) >= 2:
                    break   # 이미 이틀치 확보
                # 아직 전날치가 없으면 다음 날짜도 계속 시도
        except Exception as e:
            logger.warning("KRX API 호출 실패 (date=%s): %s", trade_date, e)

    if len(prices) >= 2:
        return prices[0], prices[1]
    if len(prices) == 1:
        return prices[0], None
    return None, None


def fetch_all() -> List[AssetPrice]:
    """모든 자산의 현재가 수집"""
    results: List[AssetPrice] = []
    for ticker, name, unit, mult in ASSETS:
        try:
            price, prev = _fetch_one(ticker)
            ap = AssetPrice(
                name=name, unit=unit,
                price=price, prev_close=prev,
                multiplier=mult,
            )
            if price:
                logger.debug("%s (%s): %.4f × %.1f", name, ticker, price, mult)
            else:
                logger.warning("%s: 데이터 없음 (ticker=%s)", name, ticker)
        except Exception as e:
            logger.error("예기치 않은 오류 (%s): %s", name, e)
            ap = AssetPrice(
                name=name, unit=unit,
                price=None, prev_close=None,
                multiplier=mult,
                error=str(e)[:120],
            )
        results.append(ap)

    # KOSPI 200 선물 — KRX API (실거래 데이터, 장중만 유효)
    price, prev = _fetch_kospi200_futures_krx()
    results.append(AssetPrice(
        name="KOSPI200선물",
        unit="pt",
        price=price,
        prev_close=prev,
        multiplier=1.0,
    ))

    return results
