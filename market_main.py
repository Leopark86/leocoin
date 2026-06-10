"""
시장 데이터 텔레그램 알림봇

WTI원유 · 달러원 · 엔원 · 미국채30년 · 미국채10년 ·
비트코인 · 금 · KOSPI · KOSPI200선물

현재가를 매시간(정각) 텔레그램으로 전송합니다.

사용법:
  python market_main.py             # 매시 정각 반복 실행
  MODE=once python market_main.py   # 1회 실행 후 종료
"""
import asyncio
import logging
import os
import sys

from dotenv import load_dotenv

load_dotenv()

log_level = os.getenv("LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=getattr(logging, log_level, logging.INFO),
    format="%(asctime)s [%(levelname)-8s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)


def _validate_env() -> tuple[str, str]:
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "").strip()
    if not token or token == "your_bot_token_here":
        logger.error("TELEGRAM_BOT_TOKEN 이 설정되지 않았습니다. .env 파일을 확인하세요.")
        sys.exit(1)
    if not chat_id or chat_id == "your_chat_id_here":
        logger.error("TELEGRAM_CHAT_ID 가 설정되지 않았습니다. .env 파일을 확인하세요.")
        sys.exit(1)
    return token, chat_id


def main() -> None:
    from src.market_notifier import MarketNotifier
    from src.market_scheduler import run_market_update, start_market_scheduler

    token, chat_id = _validate_env()
    notifier = MarketNotifier(token=token, chat_id=chat_id)
    mode = os.getenv("MODE", "scheduler").lower()

    if mode == "once":
        logger.info("1회 실행 모드")
        asyncio.run(run_market_update(notifier))
        return

    logger.info("스케줄러 모드 시작 (Ctrl+C 로 종료)")
    scheduler = start_market_scheduler(notifier)

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_forever()
    except (KeyboardInterrupt, SystemExit):
        logger.info("종료 중...")
    finally:
        scheduler.shutdown(wait=False)
        loop.close()
        logger.info("종료 완료")


if __name__ == "__main__":
    main()
