"""
APScheduler 기반 매시간 실행 스케줄러

AsyncIOScheduler를 사용하며, 시작 즉시 1회 실행 후 설정된 주기마다 반복합니다.
"""
import asyncio
import logging
import os
from datetime import datetime

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from .checker import check_camping_availability
from .notifier import TelegramNotifier

logger = logging.getLogger(__name__)


async def run_check(notifier: TelegramNotifier) -> None:
    """잔여 확인 → 텔레그램 알림 단일 실행 사이클"""
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    logger.info("[%s] 잔여 확인 시작...", ts)

    try:
        slots = await check_camping_availability()

        if slots:
            logger.info("가용 슬롯 %d개 발견 → 텔레그램 알림 전송", len(slots))
            await notifier.send_available_alert(slots)
        else:
            logger.info("예약 가능한 토요일 자리 없음")

    except Exception as exc:
        logger.error("체크 중 예외 발생: %s", exc, exc_info=True)
        try:
            await notifier.send_error_notice(str(exc))
        except Exception:
            pass


def start_scheduler(notifier: TelegramNotifier) -> AsyncIOScheduler:
    """
    매시간 run_check를 실행하는 스케줄러를 생성하고 시작합니다.
    시작 시점에 즉시 1회 실행됩니다.
    """
    interval_minutes = int(os.getenv("CHECK_INTERVAL_MINUTES", "60"))

    scheduler = AsyncIOScheduler(timezone="Asia/Seoul")
    scheduler.add_job(
        run_check,
        trigger=IntervalTrigger(minutes=interval_minutes),
        args=[notifier],
        id="nanji_camping_check",
        name=f"난지캠핑장 잔여 확인 (매 {interval_minutes}분)",
        next_run_time=datetime.now(),  # 즉시 첫 실행
        max_instances=1,              # 중복 실행 방지
        coalesce=True,                # 밀린 실행은 1회로 합산
    )
    scheduler.start()
    logger.info(
        "스케줄러 시작 — 체크 주기: %d분 / 대상: 난지캠핑장 일반캠핑존 4인용 토요일",
        interval_minutes,
    )
    return scheduler
