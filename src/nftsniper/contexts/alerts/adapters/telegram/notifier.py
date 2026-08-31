"""Telegram-нотификатор: реализация NotifierPort поверх aiogram.

Превращает AlertMessage (текст + кнопки) в Telegram-сообщение: send — отправить,
edit — заменить после решения (ТЗ §6). Кнопки-ссылки идут через url, решения —
через callback_data. ``parse_mode="HTML"``; пользовательские строки экранируются
в рендере (entrypoints/bot/render.py).
"""

from __future__ import annotations

from collections.abc import Sequence

from aiogram import Bot
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from nftsniper.contexts.alerts.domain.alert import AlertButton, AlertMessage


def build_inline_keyboard(buttons: Sequence[AlertButton]) -> InlineKeyboardMarkup:
    """AlertButton → aiogram InlineKeyboardMarkup (ссылки или callback)."""
    rows: list[list[InlineKeyboardButton]] = []
    for button in buttons:
        if button.url is not None:
            rows.append([InlineKeyboardButton(text=button.text, url=button.url)])
        elif button.callback_data is not None:
            rows.append(
                [InlineKeyboardButton(text=button.text, callback_data=button.callback_data)]
            )
    return InlineKeyboardMarkup(inline_keyboard=rows)


class TelegramNotifier:
    """NotifierPort: доставка и редактирование алертов в Telegram."""

    def __init__(self, bot: Bot) -> None:
        self._bot = bot

    async def send(self, user_id: str, message: AlertMessage) -> str:
        sent = await self._bot.send_message(
            chat_id=int(user_id),
            text=message.text,
            reply_markup=build_inline_keyboard(message.buttons) if message.buttons else None,
            parse_mode="HTML",
        )
        return str(sent.message_id)

    async def edit(self, user_id: str, message_id: str, message: AlertMessage) -> None:
        await self._bot.edit_message_text(
            text=message.text,
            chat_id=int(user_id),
            message_id=int(message_id),
            parse_mode="HTML",
        )
