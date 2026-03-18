from __future__ import annotations

import asyncio
from typing import Iterable

from aiogram import Bot

from app.db import Database, Withdrawal
from app.services.cryptobot import CryptoBotAPI, CryptoBotError


def _chunks(items: list[str], size: int) -> Iterable[list[str]]:
    for i in range(0, len(items), size):
        yield items[i : i + size]


async def invoice_watcher(*, db: Database, cryptobot: CryptoBotAPI, interval_sec: int = 10) -> None:
    while True:
        try:
            invoices = await db.list_uncredited_invoices(limit=200)
            ids = [i["invoice_id"] for i in invoices]
            for batch in _chunks(ids, 50):
                remote = await cryptobot.get_invoices(invoice_ids=batch)
                for inv in remote:
                    await db.update_invoice_status(inv.invoice_id, inv.status)
                    if inv.status == "paid":
                        await db.credit_invoice_once(inv.invoice_id)
        except asyncio.CancelledError:
            raise
        except Exception:
            # watchers must be resilient; logging can be added later
            pass
        await asyncio.sleep(max(1, interval_sec))


async def treasury_balance_watcher(*, db: Database, cryptobot: CryptoBotAPI, interval_sec: int = 1) -> None:
    while True:
        try:
            bal = await cryptobot.get_asset_balance("USDT")
            await db.set_setting("treasury_balance", str(bal))
        except asyncio.CancelledError:
            raise
        except Exception:
            pass
        await asyncio.sleep(max(1, interval_sec))


async def withdrawal_watcher(
    *,
    db: Database,
    cryptobot: CryptoBotAPI,
    bot: Bot,
    interval_sec: int = 10,
    auto_withdraw: bool = False,
) -> None:
    while True:
        try:
            if not auto_withdraw:
                await asyncio.sleep(max(1, interval_sec))
                continue

            withdrawals: list[Withdrawal] = await db.list_pending_withdrawals(limit=50)
            for w in withdrawals:
                user = await db.get_or_create_user(w.user_id)
                if user.cryptobot_id is None:
                    continue
                # "Казна" check (we track it locally and top it up via treasury invoices)
                if not await db.can_cover_from_treasury(w.net):
                    await db.set_withdrawal_status(w.withdrawal_id, status="waiting_treasury")
                    try:
                        await bot.send_message(
                            chat_id=w.user_id,
                            text=(
                                "❌ Вывод средств не удался\n"
                                "💸 В CryptoBot денег нет\n\n"
                                "⏳ Ожидайте пополнения"
                            ),
                        )
                    except Exception:
                        pass
                    continue
                try:
                    transfer = await cryptobot.transfer(user_id=user.cryptobot_id, amount=w.net, asset="USDT")
                    await db.set_withdrawal_status(w.withdrawal_id, status="done", cryptobot_transfer_id=transfer.transfer_id)
                    await db.deduct_frozen(w.user_id, w.amount)
                except (CryptoBotError, Exception):
                    await db.set_withdrawal_status(w.withdrawal_id, status="failed")
                    await db.move_frozen_to_balance(w.user_id, w.amount)
        except asyncio.CancelledError:
            raise
        except Exception:
            pass
        await asyncio.sleep(max(1, interval_sec))

