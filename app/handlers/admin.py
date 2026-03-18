from __future__ import annotations

import csv
from pathlib import Path

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, FSInputFile, Message

from app.config import Config, is_admin
from app.db import Database
from app.fsm import (
    AdminAdminsFlow,
    AdminBlacklistFlow,
    AdminBroadcastFlow,
    AdminNoteFlow,
    AdminSettingsFlow,
    AdminTopupUserFlow,
    AdminTreasuryTopupFlow,
)
from app.services.cryptobot import CryptoBotAPI, CryptoBotError
from app.ui import keyboards as kb

router = Router(name="admin")


def _deny(cb: CallbackQuery) -> bool:
    return cb.from_user is None


async def _guard_admin(cb: CallbackQuery, cfg: Config, db: Database | None = None) -> bool:
    if _deny(cb):
        await cb.answer("Доступ запрещён", show_alert=True)
        return False
    if db is not None:
        ok = await db.is_admin(cb.from_user.id, cfg.all_admin_ids)
    else:
        ok = is_admin(cb.from_user.id, cfg)
    if not ok:
        await cb.answer("Доступ запрещён", show_alert=True)
        return False
    return True


@router.callback_query(F.data == "a:panel")
async def panel(cb: CallbackQuery, cfg: Config) -> None:
    if not await _guard_admin(cb, cfg):
        return
    await cb.message.edit_text("Панель администратора", reply_markup=kb.admin_panel())
    await cb.answer()


@router.callback_query(F.data == "a:stats")
async def stats(cb: CallbackQuery, db: Database, cfg: Config) -> None:
    if not await _guard_admin(cb, cfg, db):
        return
    st = await db.request_stats()
    approved = st.get("approved", 0)
    rejected = st.get("rejected", 0)
    treasury = await db.get_treasury_balance()
    users = await db.count_users()
    await cb.message.answer(
        "📈 Статистика\n\n"
        f"✅ Успешные (approved): {approved}\n"
        f"❌ Отклонённые (rejected): {rejected}\n"
        f"🏦 Казна (USDT): {treasury:.2f}\n"
        f"👥 Пользователей: {users}",
        reply_markup=kb.admin_panel(),
    )
    await cb.answer()


@router.callback_query(F.data == "a:users")
async def users_export(cb: CallbackQuery, db: Database, cfg: Config) -> None:
    if not await _guard_admin(cb, cfg, db):
        return
    # Export users to Excel (.xlsx)
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.title = "users"
    ws.append(["user_id", "balance", "bonus", "frozen", "cryptobot_id"])
    for u in await db.list_users():
        ws.append([u.user_id, u.balance, u.bonus, u.frozen, u.cryptobot_id or ""])

    out_path = Path("users.xlsx").resolve()
    wb.save(out_path)
    await cb.message.answer_document(FSInputFile(str(out_path), filename="users.xlsx"))
    await cb.answer()


@router.callback_query(F.data == "a:topup")
async def topup_user(cb: CallbackQuery, cfg: Config, state: FSMContext) -> None:
    if not await _guard_admin(cb, cfg):
        return
    await state.set_state(AdminTopupUserFlow.user_id)
    await cb.message.answer("➕ Пополнить баланс\n\nОтправьте user_id пользователя.", reply_markup=kb.admin_cancel_menu(cancel_cb="a:topupcancel"))
    await cb.answer()


@router.callback_query(F.data == "a:topupcancel")
async def topup_cancel(cb: CallbackQuery, cfg: Config, state: FSMContext) -> None:
    if not await _guard_admin(cb, cfg):
        return
    await state.clear()
    await cb.message.edit_text("Отменено.", reply_markup=kb.admin_panel())
    await cb.answer()


@router.message(AdminTopupUserFlow.user_id)
async def topup_user_id(message: Message, state: FSMContext) -> None:
    raw = (message.text or "").strip()
    try:
        uid = int(raw)
    except ValueError:
        await message.answer("Нужно число user_id. Отправьте ещё раз.")
        return
    await state.update_data(user_id=uid)
    await state.set_state(AdminTopupUserFlow.amount)
    await message.answer("Теперь отправьте сумму в USDT (например 5).")


@router.message(AdminTopupUserFlow.amount)
async def topup_amount(message: Message, db: Database, cfg: Config, state: FSMContext) -> None:
    raw = (message.text or "").replace(",", ".").strip()
    try:
        amount = float(raw)
    except ValueError:
        await message.answer("Введите число, например 5")
        return
    if amount <= 0:
        await message.answer("Сумма должна быть больше 0")
        return
    data = await state.get_data()
    uid = int(data.get("user_id") or 0)
    if uid <= 0:
        await state.clear()
        await message.answer("Ошибка user_id.", reply_markup=kb.admin_panel())
        return
    await db.add_balance(uid, amount)
    await state.clear()
    await message.answer(f"✅ Начислено {amount:.2f} USDT пользователю {uid}.", reply_markup=kb.admin_panel())


@router.callback_query(F.data == "a:broadcast")
async def broadcast(cb: CallbackQuery, cfg: Config, state: FSMContext) -> None:
    if not await _guard_admin(cb, cfg):
        return
    await state.set_state(AdminBroadcastFlow.text)
    await cb.message.answer("📣 Рассылка\n\nОтправьте текст рассылки одним сообщением.", reply_markup=kb.admin_cancel_menu(cancel_cb="a:broadcastcancel"))
    await cb.answer()


@router.callback_query(F.data == "a:broadcastcancel")
async def broadcast_cancel(cb: CallbackQuery, cfg: Config, state: FSMContext) -> None:
    if not await _guard_admin(cb, cfg):
        return
    await state.clear()
    await cb.message.edit_text("Отменено.", reply_markup=kb.admin_panel())
    await cb.answer()


@router.message(AdminBroadcastFlow.text)
async def broadcast_send(message: Message, db: Database, cfg: Config, state: FSMContext) -> None:
    text = (message.text or "").strip()
    if not text:
        await message.answer("Пусто. Отправьте текст ещё раз.")
        return
    users = await db.list_users(limit=50000)
    sent = 0
    for u in users:
        try:
            await message.bot.send_message(chat_id=u.user_id, text=text)
            sent += 1
        except Exception:
            continue
    await state.clear()
    await message.answer(f"Готово. Отправлено: {sent}", reply_markup=kb.admin_panel())


@router.callback_query(F.data == "a:payouts")
async def payouts(cb: CallbackQuery, db: Database, cfg: Config) -> None:
    if not await _guard_admin(cb, cfg, db):
        return
    items = await db.list_pending_withdrawals(limit=50)
    if not items:
        await cb.message.answer("💸 Выплаты\n\n— pending выплат нет —", reply_markup=kb.admin_panel())
        await cb.answer()
        return
    lines = [f"#{w.withdrawal_id} user={w.user_id} amount={w.amount:.2f} net={w.net:.2f} status={w.status}" for w in items]
    await cb.message.answer("💸 Выплаты (pending)\n\n" + "\n".join(lines), reply_markup=kb.admin_panel())
    await cb.answer()


@router.callback_query(F.data == "a:reqs")
async def reqs(cb: CallbackQuery, db: Database, cfg: Config, state: FSMContext) -> None:
    if not await _guard_admin(cb, cfg, db):
        return
    await state.clear()
    items = await db.list_pending_requests(limit=50)
    text = "Очередь заявок (pending):\n" + ("\n".join([f"#{r.request_id} • {r.account_type} • {r.phone}" for r in items]) or "— пусто —")
    await cb.message.edit_text(text, reply_markup=kb.admin_requests_menu(items))
    await cb.answer()


@router.callback_query(F.data == "a:reqs:clear")
async def reqs_clear(cb: CallbackQuery, db: Database, cfg: Config) -> None:
    if not await _guard_admin(cb, cfg, db):
        return
    n = await db.clear_pending_queue()
    await cb.answer(f"Удалено: {n}", show_alert=True)
    await cb.message.edit_text("Очередь очищена.", reply_markup=kb.admin_panel())


@router.callback_query(F.data.startswith("a:req:"))
async def req_card(cb: CallbackQuery, db: Database, cfg: Config) -> None:
    if not await _guard_admin(cb, cfg, db):
        return
    parts = cb.data.split(":")
    request_id = int(parts[2])
    action = parts[3] if len(parts) > 3 else "open"

    r = await db.get_request(request_id)
    if r is None:
        await cb.answer("Не найдено", show_alert=True)
        return

    if action == "approve":
        # credit only once
        if r.status != "approved":
            await db.set_request_status(request_id, "approved")
            price = await db.get_account_type_price(r.account_type)
            if price is not None and price > 0:
                await db.add_balance(r.user_id, float(price))
                await db.append_request_log(request_id, f"credited {float(price):.2f} USDT")
                try:
                    await cb.bot.send_message(
                        chat_id=r.user_id,
                        text=f"✅ Ваша заявка #{request_id} одобрена.\nНачислено: {float(price):.2f} USDT",
                    )
                except Exception:
                    pass
        else:
            await cb.answer("Уже одобрено", show_alert=True)
    elif action == "reject":
        await db.set_request_status(request_id, "rejected")
        # notify user about rejection
        try:
            text = (
                "❌ Ваша заявка отклонена.\n\n"
                f"Заявка #{request_id}\n"
                f"Тип: {r.account_type}\n"
                f"Номер: {r.phone}"
            )
            await cb.bot.send_message(chat_id=r.user_id, text=text)
            await db.append_request_log(request_id, "rejected_notified")
        except Exception:
            pass
    elif action == "work":
        r = await db.toggle_request_flag(request_id, flag="is_work") or r
    elif action == "vip":
        r = await db.toggle_request_flag(request_id, flag="is_vip") or r
    elif action == "note":
        # handled by separate callback below
        pass
    elif action == "log":
        # handled by separate callback below
        pass
    elif action == "code":
        # Send code request message to user
        text = (
            "📨 Запрос кода\n\n"
            f"По вашей заявке #{request_id} нам нужен код подтверждения от аккаунта.\n"
            "Пожалуйста, отправьте текущий код одним сообщением в этот чат."
        )
        try:
            await cb.bot.send_message(chat_id=r.user_id, text=text)
            await db.append_request_log(request_id, "code_requested")
            await cb.answer("Запрос кода отправлен пользователю.", show_alert=True)
        except Exception:
            await cb.answer("Не удалось отправить запрос кода.", show_alert=True)

    r = await db.get_request(request_id) or r
    flags = []
    if r.is_work:
        flags.append("Ворк")
    if r.is_vip:
        flags.append("VIP")
    ftxt = f" ({', '.join(flags)})" if flags else ""
    text = (
        f"Заявка #{r.request_id}\n"
        f"User: {r.user_id}\n"
        f"Тип: {r.account_type}\n"
        f"Номер: {r.phone}\n"
        f"Статус: {r.status}{ftxt}\n"
        f"Заметка: {r.admin_note or '—'}"
    )
    await cb.message.edit_text(
        text,
        reply_markup=kb.admin_request_card(r.request_id, is_work=r.is_work, is_vip=r.is_vip),
    )
    await cb.answer()


@router.callback_query(F.data.endswith(":note"))
async def req_note(cb: CallbackQuery, cfg: Config, state: FSMContext) -> None:
    if not await _guard_admin(cb, cfg):
        return
    request_id = int(cb.data.split(":")[2])
    await state.set_state(AdminNoteFlow.text)
    await state.update_data(request_id=request_id)
    await cb.message.edit_text(
        f"Заметка для заявки #{request_id}.\nОтправьте текст одним сообщением.",
        reply_markup=kb.admin_note_menu(request_id),
    )
    await cb.answer()


@router.message(AdminNoteFlow.text)
async def req_note_save(message: Message, db: Database, state: FSMContext) -> None:
    data = await state.get_data()
    request_id = int(data.get("request_id") or 0)
    note = (message.text or "").strip()
    if not note:
        await message.answer("Пусто. Отправьте заметку ещё раз.")
        return
    await db.set_admin_note(request_id, note)
    await state.clear()
    await message.answer("Сохранено.", reply_markup=kb.back_to_menu())


@router.callback_query(F.data.endswith(":log"))
async def req_log(cb: CallbackQuery, db: Database, cfg: Config) -> None:
    if not await _guard_admin(cb, cfg, db):
        return
    request_id = int(cb.data.split(":")[2])
    r = await db.get_request(request_id)
    if r is None:
        await cb.answer("Не найдено", show_alert=True)
        return
    text = f"Лог заявки #{request_id}\n\n{r.logs or '—'}"
    await cb.message.edit_text(text, reply_markup=kb.admin_request_card(r.request_id, is_work=r.is_work, is_vip=r.is_vip))
    await cb.answer()


@router.callback_query(F.data == "a:settings")
async def settings(cb: CallbackQuery, cfg: Config, state: FSMContext) -> None:
    if not await _guard_admin(cb, cfg):
        return
    await state.clear()
    await cb.message.edit_text("Настройки", reply_markup=kb.admin_settings_menu())
    await cb.answer()


@router.callback_query(F.data == "a:set:stop")
async def settings_stop(cb: CallbackQuery, db: Database, cfg: Config) -> None:
    if not await _guard_admin(cb, cfg, db):
        return
    v = await db.toggle_stop_accepting()
    await cb.answer(f"Стоп-приём: {'включён' if v else 'выключен'}", show_alert=True)


@router.callback_query(F.data == "a:set:blacklist")
async def settings_blacklist(cb: CallbackQuery, db: Database, cfg: Config, state: FSMContext) -> None:
    if not await _guard_admin(cb, cfg, db):
        return
    await state.set_state(AdminBlacklistFlow.phone)
    items = await db.blacklist_list(limit=20)
    await cb.message.answer(
        "🚫 Чёрный список\n\n"
        f"Последние: {', '.join(items) if items else '—'}\n\n"
        "Отправьте номер для добавления (формат +7XXXXXXXXXX).",
        reply_markup=kb.admin_cancel_menu(cancel_cb='a:blacklistcancel', back_cb='a:settings'),
    )
    await cb.answer()


@router.callback_query(F.data == "a:blacklistcancel")
async def blacklist_cancel(cb: CallbackQuery, cfg: Config, state: FSMContext) -> None:
    if not await _guard_admin(cb, cfg):
        return
    await state.clear()
    await cb.message.edit_text("Отменено.", reply_markup=kb.admin_settings_menu())
    await cb.answer()


@router.message(AdminBlacklistFlow.phone)
async def blacklist_add(message: Message, db: Database, cfg: Config, state: FSMContext) -> None:
    phone = (message.text or "").strip()
    await db.blacklist_add(phone)
    await state.clear()
    await message.answer(f"✅ Добавлено в ЧС: {phone}", reply_markup=kb.admin_settings_menu())


@router.callback_query(F.data == "a:set:admins")
async def settings_admins(cb: CallbackQuery, db: Database, cfg: Config, state: FSMContext) -> None:
    if not await _guard_admin(cb, cfg, db):
        return
    extra = await db.get_extra_admin_ids()
    await state.set_state(AdminAdminsFlow.admin_id)
    await cb.message.answer(
        "👮 Администраторы\n\n"
        f"OWNER_ADMIN_ID: {cfg.owner_admin_id}\n"
        f"ADMIN_IDS (env): {', '.join(map(str, cfg.admin_ids)) if cfg.admin_ids else '—'}\n"
        f"Доп. админы (в БД): {', '.join(map(str, extra)) if extra else '—'}\n\n"
        "Отправьте user_id для добавления в доп.админы (или минус для удаления, например -123).",
        reply_markup=kb.admin_cancel_menu(cancel_cb="a:adminscancel", back_cb="a:settings"),
    )
    await cb.answer()


@router.callback_query(F.data == "a:adminscancel")
async def admins_cancel(cb: CallbackQuery, cfg: Config, state: FSMContext) -> None:
    if not await _guard_admin(cb, cfg):
        return
    await state.clear()
    await cb.message.edit_text("Отменено.", reply_markup=kb.admin_settings_menu())
    await cb.answer()


@router.message(AdminAdminsFlow.admin_id)
async def admins_update(message: Message, db: Database, cfg: Config, state: FSMContext) -> None:
    raw = (message.text or "").strip()
    try:
        v = int(raw)
    except ValueError:
        await message.answer("Нужно число. Пример: 123 или -123")
        return
    if v < 0:
        ids = await db.remove_extra_admin(abs(v))
        await message.answer(f"Удалено. Доп.админы: {', '.join(map(str, ids)) if ids else '—'}")
    else:
        ids = await db.add_extra_admin(v)
        await message.answer(f"Добавлено. Доп.админы: {', '.join(map(str, ids)) if ids else '—'}")
    await state.clear()


@router.callback_query(F.data == "a:set:maintenance")
async def settings_maintenance(cb: CallbackQuery, db: Database, cfg: Config) -> None:
    if not await _guard_admin(cb, cfg, db):
        return
    v = await db.toggle_maintenance_mode()
    await cb.answer(f"Тех. обслуживание: {'включено' if v else 'выключено'}", show_alert=True)


@router.callback_query(F.data == "a:set:backup")
async def settings_backup(cb: CallbackQuery, cfg: Config) -> None:
    if not await _guard_admin(cb, cfg):
        return
    # send DB file to chat (do not create extra copies)
    db_path = Path("bot_database.db").resolve()
    await cb.message.answer_document(FSInputFile(str(db_path), filename="bot_database.db"))
    await cb.answer()


@router.callback_query(F.data == "a:set:disputes")
async def settings_disputes(cb: CallbackQuery, cfg: Config) -> None:
    if not await _guard_admin(cb, cfg):
        return
    await cb.answer("⚖️ Споры: пока заглушка", show_alert=True)


@router.callback_query(F.data == "a:set:types")
async def settings_types(cb: CallbackQuery, db: Database, cfg: Config, state: FSMContext) -> None:
    if not await _guard_admin(cb, cfg):
        return
    full = await db.get_account_types_full()
    if full:
        cur_str = ", ".join(f"{t['name']}={t['price']:.2f} USDT" for t in full)
    else:
        cur_str = "—"
    await state.set_state(AdminSettingsFlow.account_types)
    await cb.message.edit_text(
        "Типы аккаунтов и цены.\n"
        f"Текущие: {cur_str}\n\n"
        "Формат: Telegram=1, WhatsApp=0.5\n"
        "Разделитель: запятая.",
        reply_markup=kb.back_to_menu(),
    )
    await cb.answer()


@router.message(AdminSettingsFlow.account_types)
async def settings_types_save(message: Message, db: Database, state: FSMContext) -> None:
    raw = (message.text or "").strip()
    parts = [x.strip() for x in raw.split(",") if x.strip()]
    if not parts:
        await message.answer("Пусто. Отправьте список через запятую.")
        return
    items: list[dict[str, object]] = []
    for p in parts:
        if "=" in p:
            name_part, price_part = p.split("=", 1)
            name = name_part.strip()
            try:
                price = float(price_part.replace(",", ".").strip())
            except ValueError:
                price = 0.0
        else:
            name = p
            price = 0.0
        if not name:
            continue
        items.append({"name": name, "price": price})
    if not items:
        await message.answer("Не удалось разобрать список. Пример: Telegram=1, WhatsApp=0.5")
        return
    await db.set_account_types(items)
    await state.clear()
    await message.answer("Сохранено.", reply_markup=kb.back_to_menu())


@router.callback_query(F.data == "a:set:export")
async def settings_export(cb: CallbackQuery, db: Database, cfg: Config) -> None:
    if not await _guard_admin(cb, cfg):
        return
    rows = await db.export_withdrawals_csv_rows()
    out_path = Path("withdrawals.csv").resolve()
    with out_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerows(rows)
    await cb.message.answer_document(FSInputFile(str(out_path), filename="withdrawals.csv"))
    await cb.answer()


@router.callback_query(F.data == "a:treasury")
async def treasury(cb: CallbackQuery, cfg: Config, state: FSMContext, db: Database) -> None:
    if not await _guard_admin(cb, cfg):
        return
    await state.set_state(AdminTreasuryTopupFlow.amount)
    bal = await db.get_treasury_balance()
    # Separate message (do not edit the panel message)
    await cb.message.answer(
        f"🏦 Пополнить казну\n\nТекущий баланс казны: {bal:.2f} USDT\n\nВведите сумму в USDT (например 50).",
        reply_markup=kb.admin_cancel_menu(cancel_cb="a:treasurycancel", back_cb="a:panel"),
    )
    await cb.answer()


@router.callback_query(F.data == "a:treasurycancel")
async def treasury_cancel(cb: CallbackQuery, cfg: Config, state: FSMContext) -> None:
    if not await _guard_admin(cb, cfg):
        return
    await state.clear()
    await cb.message.edit_text("Отменено.", reply_markup=kb.admin_panel())
    await cb.answer()


@router.message(AdminTreasuryTopupFlow.amount)
async def treasury_amount(message: Message, db: Database, state: FSMContext, cryptobot: CryptoBotAPI) -> None:
    raw = (message.text or "").replace(",", ".").strip()
    try:
        amount = float(raw)
    except ValueError:
        await message.answer("Введите число, например 50")
        return
    if amount <= 0:
        await message.answer("Сумма должна быть больше 0")
        return

    try:
        inv = await cryptobot.create_invoice(amount=amount, asset="USDT", description="Treasury topup")
    except (CryptoBotError, Exception):
        await state.clear()
        await message.answer("Не удалось создать инвойс. Попробуйте позже.", reply_markup=kb.admin_panel())
        return

    # Store invoice with target=treasury (invoice watcher will credit treasury_balance)
    await db.create_invoice(
        invoice_id=inv.invoice_id,
        user_id=message.from_user.id,
        amount=amount,
        status=inv.status,
        pay_url=inv.pay_url,
        target="treasury",
    )
    await state.clear()
    await message.answer(
        f"🏦 Пополнение казны\n\n"
        f"Сумма: {amount:.2f} USDT\n"
        f"Статус: {inv.status}",
        reply_markup=kb.admin_treasury_invoice_menu(inv.invoice_id, inv.pay_url),
    )


@router.callback_query(F.data.startswith("a:treasurycheck:"))
async def treasury_check(cb: CallbackQuery, db: Database, cfg: Config, cryptobot: CryptoBotAPI) -> None:
    if not await _guard_admin(cb, cfg):
        return
    invoice_id = cb.data.split(":")[2]
    try:
        invs = await cryptobot.get_invoices(invoice_ids=[invoice_id])
        if not invs:
            await cb.answer("Не найдено", show_alert=True)
            return
        inv = invs[0]
        await db.update_invoice_status(invoice_id, inv.status)
        if inv.status == "paid":
            credited = await db.credit_invoice_once(invoice_id)
            bal = await db.get_treasury_balance()
            await cb.message.edit_text(
                f"Статус: paid\nЗачислено в казну: {'да' if credited else 'уже было'}\nБаланс казны: {bal:.2f} USDT",
                reply_markup=kb.admin_panel(),
            )
        else:
            await cb.answer(f"Статус: {inv.status}", show_alert=True)
    except (CryptoBotError, Exception):
        await cb.answer("Ошибка проверки", show_alert=True)


@router.callback_query(F.data == "__never__")
async def stubs(cb: CallbackQuery, cfg: Config) -> None:
    if not await _guard_admin(cb, cfg):
        return
    await cb.answer("MVP: заглушка", show_alert=True)


@router.callback_query(F.data.in_({"a:set:disputes"}))
async def settings_stubs(cb: CallbackQuery, cfg: Config) -> None:
    if not await _guard_admin(cb, cfg):
        return
    await cb.answer("MVP: заглушка", show_alert=True)

