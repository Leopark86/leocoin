"""Telegram 알림 모듈 (python-telegram-bot v21+ async)"""
import logging
from datetime import datetime
from typing import List

from telegram import Bot
from telegram.error import TelegramError

from .checker import AvailableSlot

logger = logging.getLogger(__name__)

WEEKDAYS_KR = ["월", "화", "수", "목", "금", "토", "일"]


class TelegramNotifier:
    def __init__(self, token: str, chat_id: str) -> None:
        self._bot = Bot(token=token)
        self._chat_id = chat_id

    async def send_available_alert(self, slots: List[AvailableSlot]) -> None:
        if not slots:
            return
        await self._send(_format_available_message(slots))

    async def send_error_notice(self, error: str) -> None:
        msg = (
            "⚠️ <b>난지캠핑장 알리미 오류</b>\n\n"
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
                disable_web_page_preview=False,
            )
            logger.info("텔레그램 메시지 전송 완료")
        except TelegramError as exc:
            logger.error("텔레그램 전송 실패: %s", exc)
            raise


def _format_available_message(slots: List[AvailableSlot]) -> str:
    lines = ["🏕️ <b>난지캠핑장 잔여 자리 알림!</b>", ""]

    # 서비스별 그룹핑
    by_title: dict = {}
    for slot in sorted(slots, key=lambda s: (s.title, s.date)):
        by_title.setdefault(slot.title, []).append(slot)

    for title, title_slots in by_title.items():
        lines.append(f"📌 <b>{title}</b>")
        for slot in title_slots:
            wd = WEEKDAYS_KR[slot.date.weekday()]
            lines.append(
                f"  ✅ {slot.date.month}월 {slot.date.day}일({wd}) "
                f"— 잔여 <b>{slot.remaining}자리</b> "
                f"({slot.applied}/{slot.total})"
            )
        lines.append(f'  👉 <a href="{title_slots[0].url}">예약 바로가기</a>')
        lines.append("")

    lines.append(f"⏰ 확인 시각: {_now_str()}")
    return "\n".join(lines)


def _now_str() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")
