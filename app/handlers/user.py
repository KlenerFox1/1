from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from app.config import Config, admin_only_ids, is_admin
from app.db import Database
from app.fsm import DepositFlow, SellFlow, WithdrawFlow
from app.services.cryptobot import CryptoBotAPI, CryptoBotError
from app.ui import keyboards as kb

router = Router(name="user")


def _fmt_money(v: float) -> str:
    return f"{v:.2f} USDT"


@router.message(CommandStart())
async def cmd_start(message: Message, db: Database, cfg: Config) -> None:
    await db.get_or_create_user(message.from_user.id)
    if await db.get_stop_accepting():
        await message.answer("Приём выключен временно администрацией.")
    await message.answer(
        "Главное меню",
        reply_markup=kb.main_menu(is_admin=is_admin(message.from_user.id, cfg)),
    )


@router.callback_query(F.data == "u:menu")
async def menu(cb: CallbackQuery, db: Database, cfg: Config) -> None:
    await db.get_or_create_user(cb.from_user.id)
    await cb.message.edit_text(
        "Главное меню",
        reply_markup=kb.main_menu(is_admin=is_admin(cb.from_user.id, cfg)),
    )
    await cb.answer()


@router.callback_query(F.data == "u:sell")
async def sell(cb: CallbackQuery, db: Database, state: FSMContext) -> None:
    await state.clear()
    if await db.get_stop_accepting():
        await cb.answer("Приём выключен временно администрацией", show_alert=True)
        return
    types_ = await db.get_account_types()
    await cb.message.edit_text("Выберите тип аккаунта:", reply_markup=kb.sell_type_menu(types_))
    await cb.answer()


@router.callback_query(F.data.startswith("u:selltype:"))
async def sell_type(cb: CallbackQuery, db: Database, state: FSMContext) -> None:
    t = cb.data.split(":", 2)[2]
    await state.set_state(SellFlow.phone)
    await state.update_data(account_type=t)
    await cb.message.edit_text(
        f"Тип: {t}\n\nОтправьте номер (телефон) одним сообщением.",
        reply_markup=kb.back_to_menu(),
    )
    await cb.answer()


@router.message(SellFlow.phone)
async def sell_phone(message: Message, db: Database, state: FSMContext, cfg: Config) -> None:
    raw = (message.text or "").strip()
    # Нормализация: берём только цифры, допускаем +7 или 7..., итог должен быть 11 цифр и начинаться с 7
    digits = "".join(ch for ch in raw if ch.isdigit())
    if digits.startswith("8") and len(digits) == 11:
        digits = "7" + digits[1:]
    if digits.startswith("7") and len(digits) == 11:
        phone = "+7" + digits[1:]
    else:
        await message.answer("Номер должен быть в формате +7XXXXXXXXXX или 7XXXXXXXXXX (11 цифр). Отправьте номер ещё раз.")
        return

    if await db.get_stop_accepting():
        await state.clear()
        await message.answer("Приём заявок временно остановлен.", reply_markup=kb.back_to_menu())
        return

    data = await state.get_data()
    account_type = str(data.get("account_type") or "Unknown")
    if await db.blacklist_contains(phone):
        await state.clear()
        await message.answer("❌ Этот номер в чёрном списке.", reply_markup=kb.back_to_menu())
        return
    rid = await db.create_request(user_id=message.from_user.id, account_type=account_type, phone=phone)
    await state.clear()
    price = await db.get_account_type_price(account_type)
    price_text = f"\n💰 Цена: {price:.2f} USDT" if price is not None else ""
    await message.answer(
        f"✅ Заявка #{rid} создана и отправлена на проверку.\n"
        f"Тип: {account_type}\n"
        f"Номер: {phone}{price_text}",
        reply_markup=kb.back_to_menu(),
    )
    # Notify all admins about new request
    base_admins = admin_only_ids(cfg)
    extra_admins = set(await db.get_extra_admin_ids())
    all_admins = set(base_admins) | extra_admins
    text = (
        f"🆕 Новая заявка #{rid}\n"
        f"User: {message.from_user.id}\n"
        f"Тип: {account_type}\n"
        f"Номер: {phone}"
    )
    for admin_id in all_admins:
        try:
            await message.bot.send_message(
                chat_id=admin_id,
                text=text,
                reply_markup=kb.admin_request_card(rid, is_work=0, is_vip=0),
            )
        except Exception:
            continue


@router.message(F.text.regexp(r"^\d{4,8}$"))
async def user_code(message: Message, db: Database, cfg: Config) -> None:
    # Treat plain 4-8 digit messages as codes for the latest request
    code = (message.text or "").strip()
    reqs = await db.list_user_requests(message.from_user.id, limit=1)
    if not reqs:
        return
    r = reqs[0]
    await db.append_request_log(r.request_id, f"code={code}")
    await message.answer("✅ Код принят. Спасибо.")

    # Notify admins about received code
    base_admins = admin_only_ids(cfg)
    extra_admins = set(await db.get_extra_admin_ids())
    all_admins = set(base_admins) | extra_admins
    text = (
        f"📨 Получен код по заявке #{r.request_id}\n"
        f"User: {r.user_id}\n"
        f"Код: {code}"
    )
    for admin_id in all_admins:
        try:
            await message.bot.send_message(
                chat_id=admin_id,
                text=text,
                reply_markup=kb.admin_request_card(r.request_id, is_work=r.is_work, is_vip=r.is_vip),
            )
        except Exception:
            continue


@router.callback_query(F.data == "u:myreq")
async def my_requests(cb: CallbackQuery, db: Database) -> None:
    items = await db.list_user_requests(cb.from_user.id, limit=10)
    text = "Мои заявки:\n" + ("\n".join([f"#{r.request_id} • {r.status} • {r.account_type}" for r in items]) or "— пока пусто —")
    await cb.message.edit_text(text, reply_markup=kb.my_requests_menu(items))
    await cb.answer()


@router.callback_query(F.data.startswith("u:req:"))
async def my_request_card(cb: CallbackQuery, db: Database) -> None:
    request_id = int(cb.data.split(":")[2])
    r = await db.get_request(request_id)
    if r is None or r.user_id != cb.from_user.id:
        await cb.answer("Не найдено", show_alert=True)
        return
    flags = []
    if r.is_work:
        flags.append("Ворк")
    if r.is_vip:
        flags.append("VIP")
    ftxt = f" ({', '.join(flags)})" if flags else ""
    text = (
        f"Заявка #{r.request_id}\n"
        f"Тип: {r.account_type}\n"
        f"Номер: {r.phone}\n"
        f"Статус: {r.status}{ftxt}\n"
        f"Создана: {r.created_at}"
    )
    await cb.message.edit_text(text, reply_markup=kb.request_card_user(r.request_id))
    await cb.answer()


@router.callback_query(F.data == "u:profile")
async def profile(cb: CallbackQuery, db: Database) -> None:
    u = await db.get_or_create_user(cb.from_user.id)
    text = (
        f"Профиль\n\n"
        f"Баланс: {_fmt_money(u.balance)}\n"
        f"Бонус: {_fmt_money(u.bonus)}\n"
        f"Заморожено: {_fmt_money(u.frozen)}\n"
        f"CryptoBot ID: {u.cryptobot_id if u.cryptobot_id is not None else 'не указан'}"
    )
    await cb.message.edit_text(text, reply_markup=kb.profile_menu())
    await cb.answer()


@router.callback_query(F.data == "u:reviews")
async def reviews(cb: CallbackQuery, cfg: Config) -> None:
    if cfg.reviews_url:
        await cb.message.edit_text(f"Отзывы: {cfg.reviews_url}", reply_markup=kb.back_to_menu())
    else:
        await cb.message.edit_text("Отзывы: скоро появятся.", reply_markup=kb.back_to_menu())
    await cb.answer()


@router.callback_query(F.data == "u:deposit")
async def deposit(cb: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(DepositFlow.amount)
    await cb.message.edit_text("Введите сумму пополнения в USDT (например 10).", reply_markup=kb.back_to_menu())
    await cb.answer()


@router.message(DepositFlow.amount)
async def deposit_amount(message: Message, db: Database, cryptobot: CryptoBotAPI, state: FSMContext) -> None:
    raw = (message.text or "").replace(",", ".").strip()
    try:
        amount = float(raw)
    except ValueError:
        await message.answer("Введите число, например 10")
        return
    if amount <= 0:
        await message.answer("Сумма должна быть больше 0")
        return

    try:
        inv = await cryptobot.create_invoice(amount=amount, asset="USDT", description="Deposit")
    except (CryptoBotError, Exception):
        await state.clear()
        await message.answer("Не удалось создать инвойс. Попробуйте позже.", reply_markup=kb.back_to_menu())
        return

    await db.create_invoice(
        invoice_id=inv.invoice_id,
        user_id=message.from_user.id,
        amount=amount,
        status=inv.status,
        pay_url=inv.pay_url,
    )
    await state.clear()
    await message.answer(
        f"Инвойс создан: {amount:.2f} USDT\nСтатус: {inv.status}",
        reply_markup=kb.deposit_invoice_menu(inv.invoice_id, inv.pay_url),
    )


@router.callback_query(F.data.startswith("u:depcheck:"))
async def deposit_check(cb: CallbackQuery, db: Database, cryptobot: CryptoBotAPI) -> None:
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
            u = await db.get_or_create_user(cb.from_user.id)
            await cb.message.edit_text(
                f"Статус: paid\nЗачислено: {'да' if credited else 'уже было'}\nБаланс: {_fmt_money(u.balance)}",
                reply_markup=kb.back_to_menu(),
            )
        else:
            await cb.answer(f"Статус: {inv.status}", show_alert=True)
    except (CryptoBotError, Exception):
        await cb.answer("Ошибка проверки", show_alert=True)


@router.callback_query(F.data == "u:withdraw")
async def withdraw(cb: CallbackQuery, db: Database, state: FSMContext) -> None:
    u = await db.get_or_create_user(cb.from_user.id)
    if u.cryptobot_id is None:
        await state.set_state(WithdrawFlow.cryptobot_id)
        await cb.message.edit_text(
            "Введите ваш CryptoBot user_id (число).",
            reply_markup=kb.back_to_menu(),
        )
        await cb.answer()
        return
    await state.set_state(WithdrawFlow.amount)
    await cb.message.edit_text("Введите сумму вывода в USDT.", reply_markup=kb.back_to_menu())
    await cb.answer()


@router.message(WithdrawFlow.cryptobot_id)
async def withdraw_set_id(message: Message, db: Database, state: FSMContext) -> None:
    raw = (message.text or "").strip()
    try:
        cid = int(raw)
    except ValueError:
        await message.answer("Нужно число. Отправьте CryptoBot user_id ещё раз.")
        return
    await db.set_cryptobot_id(message.from_user.id, cid)
    await state.set_state(WithdrawFlow.amount)
    await message.answer("Ок. Теперь введите сумму вывода в USDT.")


@router.message(WithdrawFlow.amount)
async def withdraw_amount(message: Message, db: Database, state: FSMContext) -> None:
    raw = (message.text or "").replace(",", ".").strip()
    try:
        amount = float(raw)
    except ValueError:
        await message.answer("Введите число, например 5")
        return
    if amount <= 0:
        await message.answer("Сумма должна быть больше 0")
        return

    u = await db.get_or_create_user(message.from_user.id)
    if u.balance < amount:
        await message.answer(f"Недостаточно средств. Баланс: {_fmt_money(u.balance)}")
        return

    fee = 0.0
    wid = await db.create_withdrawal(user_id=message.from_user.id, amount=amount, fee=fee)
    await db.move_balance_to_frozen(message.from_user.id, amount)
    await state.clear()
    await message.answer(
        f"✅ Заявка на вывод принята #{wid}\n"
        f"Статус: pending\n"
        f"Сумма: {_fmt_money(amount)}\n"
        f"Комиссия: {_fmt_money(fee)}",
        reply_markup=kb.back_to_menu(),
    )

