"""시장 데이터 텔레그램 메시지 포맷 및 전송"""
import logging
from datetime import datetime
from typing import List

from telegram import Bot
from telegram.error import TelegramError

from .market_fetcher import AssetPrice

logger = logging.getLogger(__name__)

_EMOJI = {
    "WTI원유":       "🛢",
    "달러/원":       "💵",
    "엔/원 (100엔)": "💴",
    "미국채 30년":   "🏦",
    "미국채 10년":   "🏦",
    "비트코인":      "₿",
    "금":            "🥇",
    "KOSPI":         "📈",
    "KOSPI200선물":  "📊",
}


class MarketNotifier:
    def __init__(self, token: str, chat_id: str) -> None:
        self._bot = Bot(token=token)
        self._chat_id = chat_id

    async def send_market_update(self, prices: List[AssetPrice]) -> None:
        await self._send(_format_message(prices))

    async def send_error_notice(self, error: str) -> None:
        msg = (
            "⚠️ <b>시장 데이터 오류</b>\n\n"
            f"<code>{error[:200]}</code>\n"
            f"⏰ {_now_str()}"
        )
        await self._send(msg)

    async def _send(self, text: str) -> None:
        try:
            await self._bot.send_message(
                chat_id=self._chat_id,
                text=text,
                parse_mode="HTML",
                disable_web_page_preview=True,
            )
            logger.info("시장 데이터 메시지 전송 완료")
        except TelegramError as e:
            logger.error("텔레그램 전송 실패: %s", e)
            raise


def _fmt_price(dp: float, unit: str) -> str:
    if unit == "%":
        return f"{dp:.2f}%"
    if dp >= 10_000:
        return f"{dp:,.0f} {unit}"
    if dp >= 10:
        return f"{dp:,.2f} {unit}"
    return f"{dp:.4f} {unit}"


def _fmt_change(ch: float, chp: float, dp: float, unit: str) -> str:
    arrow = "▲" if ch >= 0 else "▼"
    sign = "+" if ch >= 0 else ""
    if unit == "%" or abs(dp) < 10:
        ch_str = f"{sign}{ch:.2f}"
    elif abs(dp) >= 10_000:
        ch_str = f"{sign}{ch:,.0f}"
    else:
        ch_str = f"{sign}{ch:,.2f}"
    return f" {arrow} {ch_str} ({sign}{chp:.2f}%)"


def _format_message(prices: List[AssetPrice]) -> str:
    now = datetime.now().strftime("%Y-%m-%d %H:%M KST")
    lines = [f"📊 <b>시장 현황</b> — {now}", ""]

    for p in prices:
        emoji = _EMOJI.get(p.name, "•")
        if p.display_price is None:
            lines.append(f"{emoji} <b>{p.name}</b>: —")
            continue

        dp = p.display_price
        price_str = _fmt_price(dp, p.unit)
        change_str = (
            _fmt_change(p.change, p.change_pct, dp, p.unit)
            if p.change is not None and p.change_pct is not None
            else ""
        )
        lines.append(f"{emoji} <b>{p.name}</b>: {price_str}{change_str}")

    return "\n".join(lines)


def _now_str() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")
