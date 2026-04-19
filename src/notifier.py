"""
Telegram 알림 모듈

python-telegram-bot v21+ (async) API를 사용합니다.
봇 토큰과 채팅 ID는 .env 파일에서 읽어옵니다.
"""
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
        """예약 가능 슬롯이 있을 때 텔레그램 메시지 전송"""
        if not slots:
            return
        message = _format_available_message(slots)
        await self._send(message)

    async def send_no_availability_notice(self) -> None:
        """잔여 없음 알림 (디버그/테스트용, 기본 비활성화)"""
        msg = (
            "🏕️ <b>난지캠핑장 잔여 확인</b>\n\n"
            "❌ 현재 예약 가능한 토요일 자리가 없습니다.\n"
            f"⏰ 확인 시각: {_now_str()}"
        )
        await self._send(msg)

    async def send_error_notice(self, error: str) -> None:
        """오류 발생 시 텔레그램 알림"""
        msg = (
            "⚠️ <b>난지캠핑장 알리미 오류</b>\n\n"
            f"오류 내용: <code>{error[:200]}</code>\n"
            f"⏰ 발생 시각: {_now_str()}"
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
    """예약 가능 슬롯 목록을 텔레그램 HTML 메시지로 포맷팅"""
    lines = [
        "🏕️ <b>난지캠핑장 잔여 자리 알림!</b>",
        "",
        f"📍 구역: <b>{slots[0].zone} ({slots[0].capacity})</b>",
        "",
        f"📅 예약 가능한 토요일 ({len(slots)}일):",
    ]

    for slot in sorted(slots, key=lambda s: s.date):
        wd = WEEKDAYS_KR[slot.date.weekday()]
        lines.append(
            f"  ✅ {slot.date.year}년 {slot.date.month}월 {slot.date.day}일 ({wd})"
        )

    lines += [
        "",
        f'👉 <a href="{slots[0].url}">예약 바로가기</a>',
        "",
        f"⏰ 확인 시각: {_now_str()}",
    ]
    return "\n".join(lines)


def _now_str() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")
