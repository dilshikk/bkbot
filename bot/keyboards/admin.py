from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ReplyKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardRemove,
)

from bot.database.models import Link, Channel

cancel_keyboard = ReplyKeyboardMarkup(
    keyboard=[[KeyboardButton(text="❌ Отмена")]],
    resize_keyboard=True,
    one_time_keyboard=True,
)

remove_keyboard = ReplyKeyboardRemove()

def admin_main_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📊 Dashboard")],
            [KeyboardButton(text="🔗 Ссылки"), KeyboardButton(text="📢 Каналы")],
            [KeyboardButton(text="📢 Рассылка"), KeyboardButton(text="👥 Пользователи")],
            [KeyboardButton(text="📱 Приложение"), KeyboardButton(text="⚙️ Настройки")],
            [KeyboardButton(text="🏠 В меню")],
        ],
        resize_keyboard=True,
    )


def links_list_keyboard(links: list[Link]) -> InlineKeyboardMarkup:
    buttons: list[list[InlineKeyboardButton]] = []
    for link in links:
        active_icon = "🟢" if link.is_active else "⚪"
        health_icon = "✅" if link.is_healthy else "❌"
        fallback_icon = "🛡️" if link.is_fallback else ""
        buttons.append([
            InlineKeyboardButton(
                text=f"{active_icon}{health_icon} {link.title} {fallback_icon}",
                callback_data=f"link_view:{link.id}",
            )
        ])
    buttons.append([
        InlineKeyboardButton(text="➕ Добавить", callback_data="link_add"),
    ])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def link_actions_keyboard(link: Link) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []

    if link.is_active:
        rows.append([InlineKeyboardButton(text="⚪ Деактивировать", callback_data=f"link_deact:{link.id}")])
    else:
        rows.append([InlineKeyboardButton(text="🟢 Сделать активной", callback_data=f"link_activate:{link.id}")])

    rows.append([
        InlineKeyboardButton(text="✏️ Изменить URL", callback_data=f"link_edit_url:{link.id}"),
        InlineKeyboardButton(text="✏️ Изменить название", callback_data=f"link_edit_title:{link.id}"),
    ])
    rows.append([
        InlineKeyboardButton(text="📅 Запланировать", callback_data=f"link_schedule:{link.id}"),
        InlineKeyboardButton(
            text="🛡️ Снять резерв" if link.is_fallback else "🛡️ Сделать резервной",
            callback_data=f"link_toggle_fallback:{link.id}",
        ),
    ])
    rows.append([InlineKeyboardButton(text="🗑 Удалить", callback_data=f"link_delete:{link.id}")])
    rows.append([InlineKeyboardButton(text="◀️ Назад", callback_data="links_back")])

    return InlineKeyboardMarkup(inline_keyboard=rows)


def channels_list_keyboard(channels: list[Channel]) -> InlineKeyboardMarkup:
    buttons: list[list[InlineKeyboardButton]] = []
    for ch in channels:
        icon = "🟢" if ch.is_active else "🔴"
        req = "🔒" if ch.is_required else "🔓"
        buttons.append([
            InlineKeyboardButton(
                text=f"{icon}{req} {ch.title}",
                callback_data=f"ch_view:{ch.id}",
            )
        ])
    buttons.append([InlineKeyboardButton(text="➕ Добавить канал", callback_data="ch_add")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def channel_actions_keyboard(ch: Channel) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="🔓 Необязательный" if ch.is_required else "🔒 Обязательный",
            callback_data=f"ch_toggle_required:{ch.id}",
        )],
        [InlineKeyboardButton(
            text="🔴 Деактивировать" if ch.is_active else "🟢 Активировать",
            callback_data=f"ch_toggle_active:{ch.id}",
        )],
        [InlineKeyboardButton(text="🔍 Проверить права бота", callback_data=f"ch_check:{ch.id}")],
        [InlineKeyboardButton(text="🗑 Удалить", callback_data=f"ch_delete:{ch.id}")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="channels_back")],
    ])
