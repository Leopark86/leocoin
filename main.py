"""
난지캠핑장 일반캠핑존 4인용 토요일 잔여 알리미

사용법:
  1. .env.example → .env 복사 후 토큰/채팅ID 입력
  2. pip install -r requirements.txt
  3. playwright install chromium
  4. python main.py            # 매시간 반복 (scheduler 모드)
  5. MODE=once python main.py  # 1회 실행 후 종료
"""
import asyncio
import logging
import os
import sys

from dotenv import load_dotenv

load_dotenv()

# ─── 로깅 설정 ────────────────────────────────────────────────
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
        logger.error(
            "TELEGRAM_BOT_TOKEN 이 설정되지 않았습니다. .env 파일을 확인하세요."
        )
        sys.exit(1)
    if not chat_id or chat_id == "your_chat_id_here":
        logger.error(
            "TELEGRAM_CHAT_ID 가 설정되지 않았습니다. .env 파일을 확인하세요."
        )
        sys.exit(1)
    return token, chat_id


async def _run_once(notifier) -> None:
    from src.scheduler import run_check
    await run_check(notifier)


def main() -> None:
    from src.notifier import TelegramNotifier
    from src.scheduler import run_check, start_scheduler

    token, chat_id = _validate_env()
    notifier = TelegramNotifier(token=token, chat_id=chat_id)
    mode = os.getenv("MODE", "scheduler").lower()

    if mode == "once":
        logger.info("1회 실행 모드")
        asyncio.run(run_check(notifier))
        return

    # ── 스케줄러 모드 ─────────────────────────────────────────
    logger.info("스케줄러 모드 시작 (Ctrl+C 로 종료)")
    scheduler = start_scheduler(notifier)

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
