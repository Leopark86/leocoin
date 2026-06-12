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
    ("EWY",      "EWY",             "USD",     1.0),
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


def _krx_fetch_one_day(trade_date: str) -> Optional[float]:
    """KRX API에서 특정 날짜 KOSPI200선물 종가 하나 반환. 실패 시 None."""
    attempts = [
        {"bld": "dbms/MDC/STAT/standard/MDCSTAT13001",
         "locale": "ko_KR", "trdDd": trade_date, "mktId": "F"},
        {"bld": "dbms/MDC/STAT/standard/MDCSTAT13001",
         "locale": "ko_KR", "trdDd": trade_date},
        {"bld": "dbms/MDC/STAT/standard/MDCSTAT13501",
         "locale": "ko_KR", "trdDd": trade_date},
    ]
    for params in attempts:
        bld = params["bld"]
        try:
            resp = requests.post(
                "https://data.krx.co.kr/comm/bldAttendant/getJsonData.cmd",
                data=params, headers=_KRX_HEADERS, timeout=10,
            )
            if resp.status_code != 200:
                logger.warning("KRX API HTTP %d (bld=%s, date=%s)",
                               resp.status_code, bld, trade_date)
                continue

            body = resp.json()
            items = body.get("output", [])

            if not items:
                # 응답은 왔지만 output 없음 — 키 목록 로그
                logger.warning("KRX API output 없음 (bld=%s, date=%s) 키: %s",
                               bld, trade_date, list(body.keys()))
                continue

            # 첫 실행 시 응답 구조 확인용 로그 (다음 배포 후 제거 가능)
            logger.warning("KRX API 응답 샘플 (bld=%s, date=%s, 항목수=%d): %s",
                           bld, trade_date, len(items), str(items[0])[:300])

            for item in items:
                nm = (item.get("prodNm") or item.get("itemNm") or
                      item.get("PROD_NM") or "").replace(" ", "")
                pid = (item.get("prodId") or item.get("itemCode") or
                       item.get("PROD_ID") or item.get("ISU_CD") or "")
                if "코스피200선물" in nm or "F102" in pid or pid.startswith("101"):
                    for key in ("trdPrc", "clsPrc", "closPrc", "tddClsprc",
                                "TDD_CLSPRC", "CLSPRC"):
                        raw = item.get(key)
                        if raw:
                            return float(str(raw).replace(",", ""))
        except Exception as e:
            logger.warning("KRX API 예외 (bld=%s, date=%s): %s", bld, trade_date, e)
    return None


def _fetch_kospi200_futures_yf() -> tuple[Optional[float], Optional[float]]:
    """Yahoo Finance CME KOSPI200 선물 티커 시도"""
    # CME Micro/Mini KOSPI 200 futures: KM=F, KO=F, KP=F, KS=F
    for ticker in ["KM=F", "KO=F", "KP=F", "KS=F"]:
        try:
            price, prev = _fetch_one(ticker)
            if price is not None and price > 0:
                logger.warning("KOSPI200선물 Yahoo Finance 성공: %s = %.2f", ticker, price)
                return price, prev
        except Exception as e:
            logger.debug("Yahoo Finance KOSPI200선물 실패 (%s): %s", ticker, e)
    logger.warning("Yahoo Finance: KOSPI200선물 데이터 없음 (KM=F, KO=F, KP=F, KS=F 모두 실패)")
    return None, None


def _fetch_kospi200_futures_naver() -> tuple[Optional[float], Optional[float]]:
    """Naver Finance API로 KOSPI200 선물 조회"""
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
        "Referer": "https://finance.naver.com",
    }
    # Naver Finance 선물 API 엔드포인트 후보
    endpoints = [
        "https://m.stock.naver.com/api/domestic/index/KOSPI200/futures",
        "https://m.stock.naver.com/api/stock/futures/101T3000/basic",
        "https://finance.naver.com/sise/futures_index.naver?code=KOSPI200",
    ]
    for url in endpoints:
        try:
            resp = requests.get(url, headers=headers, timeout=10)
            logger.warning("Naver API 응답 (url=%s, status=%d): %.300s",
                           url, resp.status_code, resp.text)
            if resp.status_code != 200:
                continue
            data = resp.json()
            # 응답 구조 탐색
            for key in ("closePrice", "price", "closeValue", "currentPrice",
                        "lastPrice", "tddClsprc", "clsprc"):
                val = data.get(key)
                if val is not None:
                    try:
                        price = float(str(val).replace(",", ""))
                        if price > 0:
                            prev_val = data.get("previousClosePrice") or data.get("prevClosePrice")
                            prev = float(str(prev_val).replace(",", "")) if prev_val else None
                            logger.warning("Naver API KOSPI200선물 성공: %.2f (key=%s)", price, key)
                            return price, prev
                    except (ValueError, TypeError):
                        continue
        except Exception as e:
            logger.debug("Naver API 실패 (%s): %s", url, e)
    logger.warning("Naver API: KOSPI200선물 데이터 없음")
    return None, None


def _fetch_kospi200_futures_krx() -> tuple[Optional[float], Optional[float]]:
    """KRX API → FDR → Yahoo Finance → Naver 순으로 KOSPI200선물 최근월물 종가 조회"""
    # 1차: KRX 데이터포털
    prices: list[float] = []
    for delta in range(7):
        trade_date = (date.today() - timedelta(days=delta)).strftime("%Y%m%d")
        p = _krx_fetch_one_day(trade_date)
        if p is not None:
            prices.append(p)
            if len(prices) >= 2:
                break
    if prices:
        return (prices[0], prices[1]) if len(prices) >= 2 else (prices[0], None)

    # 2차: FinanceDataReader
    try:
        import FinanceDataReader as fdr
        end_dt = date.today().strftime("%Y-%m-%d")
        start_dt = (date.today() - timedelta(days=10)).strftime("%Y-%m-%d")
        for ticker in ["KS200F", "KSF", "F102"]:
            try:
                df = fdr.DataReader(ticker, start_dt, end_dt)
                if df is not None and not df.empty:
                    closes = df["Close"].dropna()
                    if len(closes) >= 2:
                        return float(closes.iloc[-1]), float(closes.iloc[-2])
                    if len(closes) == 1:
                        return float(closes.iloc[-1]), None
            except Exception:
                continue
        logger.warning("FDR: 코스피200선물 데이터 없음")
    except ImportError:
        pass
    except Exception as e:
        logger.warning("FDR 조회 실패: %s", e)

    # 3차: Yahoo Finance CME 티커
    result = _fetch_kospi200_futures_yf()
    if result[0] is not None:
        return result

    # 4차: Naver Finance API
    return _fetch_kospi200_futures_naver()


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

    # KOSPI 200 선물 — KRX/FDR/YF/Naver 순으로 조회
    price, prev = _fetch_kospi200_futures_krx()
    results.append(AssetPrice(
        name="KOSPI200선물",
        unit="pt",
        price=price,
        prev_close=prev,
        multiplier=1.0,
    ))

    return results
