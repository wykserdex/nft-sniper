"""Точка входа Telegram-бота: сборка и запуск long polling.

    nftsniper bot

Требует NFT_TELEGRAM_BOT_TOKEN. До  данные живут в in-memory
адаптерах (adapters.py); Postgres/Redis подключатся позже.
"""

from __future__ import annotations

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage

from nftsniper.config.settings import Settings, get_settings
from nftsniper.entrypoints.bot.adapters import (
    InMemoryAlertRegistry,
    InMemoryDecisionStore,
    InMemoryUserSettingsStore,
    InMemoryWatchlistStore,
)
from nftsniper.entrypoints.bot.handlers import build_router
from nftsniper.entrypoints.bot.service import BotService
from nftsniper.observability.logging import get_logger

logger = get_logger(__name__)


def create_bot(settings: Settings) -> Bot:
    """aiogram Bot из настроек (токен обязателен)."""
    if settings.telegram_bot_token is None:
        msg = "NFT_TELEGRAM_BOT_TOKEN не задан — бот не может стартовать"
        raise RuntimeError(msg)
    return Bot(
        token=settings.telegram_bot_token.get_secret_value(),
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )


def build_service() -> BotService:
    """BotService на in-memory адаптерах (MVP, до)."""
    return BotService(
        settings=InMemoryUserSettingsStore(),
        watchlist=InMemoryWatchlistStore(),
        decisions=InMemoryDecisionStore(),
        registry=InMemoryAlertRegistry(),
    )


def build_dispatcher(service: BotService | None = None) -> Dispatcher:
    """Dispatcher с роутером бота и MemoryStorage (FSM)."""
    dispatcher = Dispatcher(storage=MemoryStorage())
    dispatcher.include_router(build_router(service if service is not None else build_service()))
    return dispatcher


async def run_bot(settings: Settings | None = None) -> None:
    """Запуск long polling (не возвращается до остановки)."""
    effective = settings if settings is not None else get_settings()
    bot = create_bot(effective)
    dispatcher = build_dispatcher()
    logger.info("bot_starting", env=effective.app_env)
    await dispatcher.start_polling(bot)
