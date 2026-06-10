"""시장 데이터 정시(매시 0분) APScheduler"""
import logging
from datetime import datetime

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from .market_fetcher import fetch_all
from .market_notifier import MarketNotifier

logger = logging.getLogger(__name__)


async def run_market_update(notifier: MarketNotifier) -> None:
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    logger.info("[%s] 시장 데이터 수집 시작", ts)
    try:
        prices = fetch_all()
        await notifier.send_market_update(prices)
    except Exception as e:
        logger.error("시장 데이터 업데이트 실패: %s", e, exc_info=True)
        try:
            await notifier.send_error_notice(str(e))
        except Exception:
            pass


def start_market_scheduler(notifier: MarketNotifier) -> AsyncIOScheduler:
    """매시 정각 실행 스케줄러 (시작 즉시 1회 실행)"""
    scheduler = AsyncIOScheduler(timezone="Asia/Seoul")
    scheduler.add_job(
        run_market_update,
        trigger=CronTrigger(minute=0, timezone="Asia/Seoul"),
        args=[notifier],
        id="market_hourly",
        name="시장 데이터 정시 알림",
        next_run_time=datetime.now(),
        max_instances=1,
        coalesce=True,
    )
    scheduler.start()
    logger.info("시장 스케줄러 시작 — 매시 정각 실행")
    return scheduler
