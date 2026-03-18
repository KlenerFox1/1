from __future__ import annotations

from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.db import Request


def main_menu(*, is_admin: bool) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="🛒 Продать аккаунт", callback_data="u:sell")
    kb.button(text="📋 Мои заявки", callback_data="u:myreq")
    kb.adjust(2)
    kb.button(text="💸 Вывести", callback_data="u:withdraw")
    kb.button(text="👤 Профиль", callback_data="u:profile")
    kb.adjust(2)
    kb.button(text="⭐ Отзывы", callback_data="u:reviews")
    kb.adjust(1)
    if is_admin:
        kb.button(text="🛠 Панель администратора", callback_data="a:panel")
        kb.adjust(1)
    return kb.as_markup()


def back_to_menu() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="⬅️ В меню", callback_data="u:menu")
    return kb.as_markup()


def sell_type_menu(types_: list[str]) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for t in types_:
        kb.button(text=t, callback_data=f"u:selltype:{t}")
    kb.adjust(2)
    kb.button(text="⬅️ В меню", callback_data="u:menu")
    kb.adjust(1)
    return kb.as_markup()


def my_requests_menu(requests: list[Request]) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for r in requests:
        kb.button(text=f"#{r.request_id} • {r.status}", callback_data=f"u:req:{r.request_id}")
    kb.adjust(1)
    kb.button(text="⬅️ В меню", callback_data="u:menu")
    kb.adjust(1)
    return kb.as_markup()


def request_card_user(request_id: int) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="⬅️ Назад", callback_data="u:myreq")
    kb.button(text="В меню", callback_data="u:menu")
    kb.adjust(2)
    return kb.as_markup()


def profile_menu() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="⬅️ В меню", callback_data="u:menu")
    kb.adjust(1)
    return kb.as_markup()


def deposit_invoice_menu(invoice_id: str, pay_url: str | None) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    if pay_url:
        kb.button(text="💳 Оплатить", url=pay_url)
    kb.button(text="🔎 Проверить", callback_data=f"u:depcheck:{invoice_id}")
    kb.adjust(1)
    kb.button(text="⬅️ В меню", callback_data="u:menu")
    kb.adjust(1)
    return kb.as_markup()


def admin_treasury_invoice_menu(invoice_id: str, pay_url: str | None) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    if pay_url:
        kb.button(text="💳 Оплатить", url=pay_url)
    kb.button(text="🔎 Проверить", callback_data=f"a:treasurycheck:{invoice_id}")
    kb.adjust(1)
    kb.button(text="🛠 Панель", callback_data="a:panel")
    kb.adjust(1)
    return kb.as_markup()


def admin_cancel_menu(*, cancel_cb: str, back_cb: str = "a:panel") -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="❌ Отмена", callback_data=cancel_cb)
    kb.button(text="⬅️ Назад", callback_data=back_cb)
    kb.adjust(2)
    return kb.as_markup()


def admin_note_menu(request_id: int) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="⬅️ Назад к заявке", callback_data=f"a:req:{request_id}")
    kb.button(text="🛠 Панель", callback_data="a:panel")
    kb.adjust(2)
    return kb.as_markup()


def admin_panel() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="🗂 Заявки", callback_data="a:reqs")
    kb.button(text="👥 Пользователи", callback_data="a:users")
    kb.button(text="➕ Пополнить баланс", callback_data="a:topup")
    kb.adjust(3)
    kb.button(text="📈 Статистика", callback_data="a:stats")
    kb.button(text="🏦 Пополнить казну", callback_data="a:treasury")
    kb.button(text="💸 Выплаты", callback_data="a:payouts")
    kb.adjust(3)
    kb.button(text="📣 Рассылка", callback_data="a:broadcast")
    kb.adjust(1)
    kb.button(text="⚙️ Настройки", callback_data="a:settings")
    kb.adjust(1)
    kb.button(text="⬅️ В меню", callback_data="u:menu")
    kb.adjust(1)
    return kb.as_markup()


def admin_requests_menu(requests: list[Request]) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for r in requests:
        kb.button(text=f"#{r.request_id} • {r.account_type}", callback_data=f"a:req:{r.request_id}")
    kb.adjust(1)
    kb.button(text="🧹 Очистить очередь", callback_data="a:reqs:clear")
    kb.button(text="⬅️ Назад", callback_data="a:panel")
    kb.adjust(2)
    return kb.as_markup()


def admin_request_card(request_id: int, *, is_work: int, is_vip: int) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="✅ Одобрить", callback_data=f"a:req:{request_id}:approve")
    kb.button(text=("🧰 Ворк ✅" if is_work else "🧰 Ворк"), callback_data=f"a:req:{request_id}:work")
    kb.button(text=("💎 VIP ✅" if is_vip else "💎 VIP"), callback_data=f"a:req:{request_id}:vip")
    kb.adjust(3)
    kb.button(text="❌ Отклонить", callback_data=f"a:req:{request_id}:reject")
    kb.button(text="📝 Заметка", callback_data=f"a:req:{request_id}:note")
    kb.button(text="📜 Лог", callback_data=f"a:req:{request_id}:log")
    kb.button(text="📨 Запросить код", callback_data=f"a:req:{request_id}:code")
    kb.adjust(4)
    kb.button(text="⬅️ Назад", callback_data="a:reqs")
    kb.button(text="🛠 Панель", callback_data="a:panel")
    kb.adjust(2)
    return kb.as_markup()


def admin_settings_menu() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="🧾 Типы аккаунтов", callback_data="a:set:types")
    kb.button(text="⛔ Стоп-приём", callback_data="a:set:stop")
    kb.button(text="🚫 Чёрный список", callback_data="a:set:blacklist")
    kb.button(text="📤 Экспорт CSV", callback_data="a:set:export")
    kb.adjust(4)
    kb.button(text="👮 Администраторы", callback_data="a:set:admins")
    kb.button(text="🛠 Тех. обслуживание", callback_data="a:set:maintenance")
    kb.button(text="⚖️ Споры", callback_data="a:set:disputes")
    kb.button(text="💾 Бэкап БД", callback_data="a:set:backup")
    kb.adjust(4)
    kb.button(text="⬅️ Назад", callback_data="a:panel")
    kb.adjust(1)
    return kb.as_markup()

