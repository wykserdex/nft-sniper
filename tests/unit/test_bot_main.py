"""Точка входа бота: create_bot, build_service, build_dispatcher."""

import pytest
from aiogram import Bot
from pydantic import SecretStr

from nftsniper.config.settings import Settings
from nftsniper.entrypoints.bot.main import build_dispatcher, build_service, create_bot
from nftsniper.entrypoints.bot.service import BotService


def test_create_bot_requires_token() -> None:
    settings = Settings(_env_file=None, telegram_bot_token=None)
    with pytest.raises(RuntimeError, match="NFT_TELEGRAM_BOT_TOKEN"):
        create_bot(settings)


def test_create_bot_with_token() -> None:
    settings = Settings(_env_file=None, telegram_bot_token=SecretStr("123:ABC"))
    bot = create_bot(settings)
    assert isinstance(bot, Bot)


def test_build_service_returns_bot_service() -> None:
    assert isinstance(build_service(), BotService)


def test_build_dispatcher_without_service() -> None:
    dispatcher = build_dispatcher()
    assert dispatcher is not None
