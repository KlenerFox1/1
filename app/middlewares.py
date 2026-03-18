from __future__ import annotations

from typing import Any, Awaitable, Callable, Dict

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject

from app.config import Config
from app.db import Database
from app.services.cryptobot import CryptoBotAPI


class AppContextMiddleware(BaseMiddleware):
    def __init__(self, *, db: Database, cfg: Config, cryptobot: CryptoBotAPI) -> None:
        self._db = db
        self._cfg = cfg
        self._cryptobot = cryptobot

    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any],
    ) -> Any:
        data["db"] = self._db
        data["cfg"] = self._cfg
        data["cryptobot"] = self._cryptobot
        return await handler(event, data)
