from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from aiogram import Bot, Dispatcher
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.client.default import DefaultBotProperties
from aiogram.exceptions import TelegramNetworkError
from aiogram.fsm.storage.memory import MemoryStorage
from dotenv import load_dotenv

from app.config import load_config
from app.db import Database
from app.handlers import admin as admin_handlers
from app.handlers import user as user_handlers
from app.middlewares import AppContextMiddleware
from app.services.cryptobot import CryptoBotAPI
from app.services.payments import invoice_watcher, treasury_balance_watcher, withdrawal_watcher


async def main() -> None:
    # Load .env from the same directory as main.py
    env_path = Path(__file__).with_name(".env")
    if not env_path.exists():
        raise RuntimeError(f".env not found next to main.py: {env_path}")

    # override=True is important on Windows when env vars exist but are empty/old
    loaded = load_dotenv(dotenv_path=env_path, override=True, encoding="utf-8")
    if not loaded:
        raise RuntimeError(f"Failed to load .env: {env_path}")

    # Fallback: also try current working directory
    load_dotenv(override=True, encoding="utf-8")
    cfg = load_config()

    logging.basicConfig(level=logging.INFO)

    db = Database(Path("bot_database.db").resolve())
    await db.connect()

    cryptobot = CryptoBotAPI(cfg.cryptobot_api_key)

    session = AiohttpSession(timeout=60)
    bot = Bot(token=cfg.bot_token, session=session, default=DefaultBotProperties(parse_mode="HTML"))
    dp = Dispatcher(storage=MemoryStorage())

    dp.update.middleware(AppContextMiddleware(db=db, cfg=cfg, cryptobot=cryptobot))

    dp.include_router(user_handlers.router)
    dp.include_router(admin_handlers.router)

    watcher_tasks: list[asyncio.Task] = [
        asyncio.create_task(invoice_watcher(db=db, cryptobot=cryptobot, interval_sec=cfg.watcher_interval_sec)),
        asyncio.create_task(treasury_balance_watcher(db=db, cryptobot=cryptobot, interval_sec=1)),
        asyncio.create_task(
            withdrawal_watcher(
                db=db,
                cryptobot=cryptobot,
                bot=bot,
                interval_sec=cfg.watcher_interval_sec,
                auto_withdraw=cfg.auto_withdraw,
            )
        ),
    ]

    try:
        # Wait for Telegram API to become reachable (prevents startup crash on transient network issues)
        delay = 2
        for attempt in range(1, 11):
            try:
                await bot.get_me()
                break
            except TelegramNetworkError:
                logging.warning("Telegram network timeout (attempt %s/10). Retrying in %ss...", attempt, delay)
                await asyncio.sleep(delay)
                delay = min(30, delay * 2)
        await dp.start_polling(bot)
    finally:
        for t in watcher_tasks:
            t.cancel()
        await asyncio.gather(*watcher_tasks, return_exceptions=True)
        await cryptobot.aclose()
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())

