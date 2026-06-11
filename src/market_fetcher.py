"""시장 데이터 수집 모듈 (yfinance 기반)"""
import logging
from dataclasses import dataclass
from typing import List, Optional

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


def _fetch_kospi200_futures_pykrx() -> tuple[Optional[float], Optional[float]]:
    """
    pykrx로 KOSPI 200 선물 최근월물 종가 조회.
    KRX 장중(09:00~15:45 KST) 데이터만 가능, 야간선물은 미지원.
    """
    from datetime import date, timedelta
    try:
        from pykrx import stock
        today = date.today()
        date_str = today.strftime("%Y%m%d")
        week_ago = (today - timedelta(days=7)).strftime("%Y%m%d")

        # KOSPI 200 선물 종목 목록 조회 (KRX 코드 "101"로 시작)
        tickers = stock.get_futures_ticker_list(date_str)
        k200 = sorted([t for t in tickers if t.startswith("101")])
        if not k200:
            logger.debug("pykrx: 코스피200선물 종목 없음 (date=%s)", date_str)
            return None, None

        front = k200[0]  # 최근월물
        logger.debug("pykrx 코스피200선물 최근월물 티커: %s", front)

        df = stock.get_futures_ohlcv_by_date(week_ago, date_str, front)
        if df is not None and not df.empty:
            closes = df["종가"].dropna()
            if len(closes) >= 2:
                return float(closes.iloc[-1]), float(closes.iloc[-2])
            if len(closes) == 1:
                return float(closes.iloc[-1]), None
    except Exception as e:
        logger.debug("pykrx KOSPI200선물 조회 실패: %s", e)
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

    # KOSPI 200 선물 — pykrx (실거래 데이터, 장중만 유효)
    price, prev = _fetch_kospi200_futures_pykrx()
    results.append(AssetPrice(
        name="KOSPI200선물",
        unit="pt",
        price=price,
        prev_close=prev,
        multiplier=1.0,
    ))

    return results
