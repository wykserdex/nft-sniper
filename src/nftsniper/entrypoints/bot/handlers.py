"""Хендлеры бота (aiogram 3): команды, FSM настроек, решения.

Хендлеры — тонкие: достают данные из Telegram-типов и вызывают BotService.
Сборка роутера через ``build_router(service)``, чтобы в тестах подставить
fake'овые хранилища.
"""

from __future__ import annotations

from datetime import UTC, datetime

from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message

from nftsniper.entrypoints.bot.i18n import get_strings
from nftsniper.entrypoints.bot.keyboards import (
    parse_setting_callback,
    settings_menu_keyboard,
)
from nftsniper.entrypoints.bot.render import parse_decision_cb
from nftsniper.entrypoints.bot.service import BotService


class SettingsState(StatesGroup):
    """FSM /settings: ждём значение одного поля."""

    waiting_value = State()


def build_router(service: BotService) -> Router:
    """Собрать роутер со всеми командами и callback-хендлерами."""
    router = Router(name="nft-sniper-bot")
    _register_commands(router, service)
    _register_callbacks(router, service)
    return router


def _register_commands(router: Router, service: BotService) -> None:
    @router.message(CommandStart())
    async def on_start(message: Message) -> None:
        language = message.from_user.language_code if message.from_user else None
        text = await service.start_text(_user_id(message), language)
        await message.answer(text)

    @router.message(Command("help"))
    async def on_help(message: Message) -> None:
        await message.answer(await service.help_text(_user_id(message)))

    @router.message(Command("settings"))
    async def on_settings(message: Message, state: FSMContext) -> None:
        await state.clear()
        user_id = _user_id(message)
        await message.answer(
            await service.settings_prompt(user_id), reply_markup=await _menu(user_id, service)
        )

    @router.message(Command("watchlist"))
    async def on_watchlist(message: Message) -> None:
        await message.answer(await service.watchlist_text(_user_id(message)))

    @router.message(Command("mute"))
    async def on_mute(message: Message) -> None:
        await message.answer(await service.mute_text(_user_id(message)))

    @router.message(Command("stats"))
    async def on_stats(message: Message) -> None:
        await message.answer(await service.stats_text(_user_id(message)))

    @router.message(Command("pause"))
    async def on_pause(message: Message) -> None:
        await message.answer(await service.pause(_user_id(message), paused=True))

    @router.message(Command("resume"))
    async def on_resume(message: Message) -> None:
        await message.answer(await service.pause(_user_id(message), paused=False))

    @router.message(Command("cancel"))
    async def on_cancel(message: Message, state: FSMContext) -> None:
        await state.clear()
        s = get_strings(await service.lang(_user_id(message)))
        await message.answer(s.settings_cancelled)

    @router.message(SettingsState.waiting_value)
    async def on_setting_value(message: Message, state: FSMContext) -> None:
        data = await state.get_data()
        field = data.get("field")
        if not isinstance(field, str):
            await state.clear()
            return
        ok, text = await service.apply_setting(_user_id(message), field, message.text or "")
        if ok:
            await state.clear()
            await message.answer(text, reply_markup=await _menu(_user_id(message), service))
        else:
            await message.answer(text)


def _register_callbacks(router: Router, service: BotService) -> None:
    @router.callback_query(F.data.startswith("set:"))
    async def on_settings_callback(callback: CallbackQuery, state: FSMContext) -> None:
        field = parse_setting_callback(callback.data or "")
        if field is None:
            await callback.answer()
            return
        user_id = _user_id(callback)
        if field == "lang":
            await callback.answer()
            text = await service.toggle_language(user_id)
            await _edit_menu(callback, text, user_id, service)
            return
        if field == "done":
            await state.clear()
            await callback.answer(text=await service.settings_saved_text(user_id))
            return
        await state.set_state(SettingsState.waiting_value)
        await state.update_data(field=field)
        await callback.answer()
        if isinstance(callback.message, Message):
            await callback.message.answer(await service.ask_field_text(user_id, field))

    @router.callback_query(F.data.startswith("dec:"))
    async def on_decision_callback(callback: CallbackQuery) -> None:
        parsed = parse_decision_cb(callback.data or "")
        if parsed is None:
            await callback.answer()
            return
        action, alert_id = parsed
        latency_ms = _latency_ms(_message_date(callback))
        result = await service.handle_decision(
            _user_id(callback), action, alert_id, latency_ms=latency_ms
        )
        await callback.answer(text=result.popup)
        if isinstance(callback.message, Message):
            await callback.message.edit_text(result.edited.text)


# ── вспомогательные ─────────────────────────────────────────────────────


def _user_id(message: Message | CallbackQuery) -> str:
    user = message.from_user
    return str(user.id) if user is not None else "0"


async def _menu(user_id: str, service: BotService) -> InlineKeyboardMarkup:
    lang = await service.lang(user_id)
    return settings_menu_keyboard(lang)


async def _edit_menu(callback: CallbackQuery, text: str, user_id: str, service: BotService) -> None:
    if isinstance(callback.message, Message):
        await callback.message.edit_text(text, reply_markup=await _menu(user_id, service))


def _message_date(callback: CallbackQuery) -> datetime | None:
    """Дата сообщения колбэка; недоступное сообщение → None."""
    if isinstance(callback.message, Message):
        return callback.message.date
    return None


def _latency_ms(message_date: datetime | None) -> int:
    """Латентность решения: от даты сообщения до сейчас (мс, ТЗ §5)."""
    if message_date is None:
        return 0
    now = datetime.now(UTC)
    delta = now - message_date
    return max(0, int(delta.total_seconds() * 1000))
