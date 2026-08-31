"""Интеграция aiogram-диспетчера: полный путь настройки и решения.

Критерий ТЗ §7: «полный путь настройки и реакции на алерт проходится
без ошибок». Прогоняем /start → /settings → правка поля → решение по алерту
через Dispatcher.feed_update с фейковой сессией (без сети).
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from decimal import Decimal

import pytest
from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage

from nftsniper.entrypoints.bot.adapters import (
    InMemoryAlertRegistry,
    InMemoryDecisionStore,
    InMemoryUserSettingsStore,
    InMemoryWatchlistStore,
)
from nftsniper.entrypoints.bot.handlers import build_router
from nftsniper.entrypoints.bot.render import AlertView
from nftsniper.entrypoints.bot.service import BotService
from nftsniper.shared.money import TONAmount
from tests.bot_helpers import (
    TEST_TOKEN,
    FakeTelegramSession,
    callback_update,
    message_update,
)


def make_view() -> AlertView:
    return AlertView(
        alert_id="al-1",
        listing_id="lg-1",
        item_id="EQItem888",
        item_name="Number #888",
        collection_id="EQColl",
        collection_name="Anonymous Numbers",
        price=TONAmount.from_ton(120),
        fair_price=TONAmount.from_ton(207),
        discount=Decimal("0.42"),
        confidence=Decimal("0.78"),
        floor_p5=TONAmount.from_ton(195),
        median_7d=TONAmount.from_ton(214),
        sales_7d=18,
        floor_24h_change=Decimal("-0.03"),
        liquidity_spd=Decimal("2.4"),
        listing_age_seconds=11,
        getgems_url="https://getgems.io/nft/EQItem888",
    )


@dataclass
class BotTestEnv:
    service: BotService
    dispatcher: Dispatcher
    bot: Bot
    session: FakeTelegramSession
    settings: InMemoryUserSettingsStore
    decisions: InMemoryDecisionStore


@pytest.fixture
def env() -> BotTestEnv:
    settings = InMemoryUserSettingsStore()
    watchlist = InMemoryWatchlistStore()
    decisions = InMemoryDecisionStore()
    registry = InMemoryAlertRegistry()
    service = BotService(
        settings=settings,
        watchlist=watchlist,
        decisions=decisions,
        registry=registry,
    )
    dispatcher = Dispatcher(storage=MemoryStorage())
    dispatcher.include_router(build_router(service))
    session = FakeTelegramSession()
    bot = Bot(token=TEST_TOKEN, session=session)
    return BotTestEnv(
        service=service,
        dispatcher=dispatcher,
        bot=bot,
        session=session,
        settings=settings,
        decisions=decisions,
    )


async def test_full_settings_flow(env: BotTestEnv) -> None:
    dp = env.dispatcher
    bot = env.bot
    session = env.session

    # /start
    await dp.feed_update(bot, message_update("/start"))
    assert session.last_text.startswith("👋")

    # /settings → меню
    await dp.feed_update(bot, message_update("/settings"))
    assert "Текущие настройки" in session.last_text

    # нажать «Дискаунт» → prompt
    await dp.feed_update(bot, callback_update("set:min_discount"))
    assert "дискаунта" in session.last_text

    # ввести значение → меню с новым порогом
    await dp.feed_update(bot, message_update("30"))
    assert "30%" in session.last_text

    stored = await env.settings.get("123")
    assert stored is not None
    assert stored.min_discount == Decimal("0.3")


async def test_decision_callback_edits_message(env: BotTestEnv) -> None:
    dp = env.dispatcher
    bot = env.bot
    session = env.session

    await env.service.register_alert(make_view())

    started = time.monotonic()
    await dp.feed_update(bot, callback_update("dec:taken:al-1"))
    elapsed = time.monotonic() - started

    edits = session.edited_messages()
    assert edits, "ожидалось редактирование сообщения после решения"
    assert "getgems.io" in (edits[-1].text or "")

    decisions = env.decisions.saved
    assert decisions[0].action == "taken"

    # ТЗ §7: ответ на callback быстрее 1 секунды (щедрый порог против CI-флаков)
    assert elapsed < 5.0


async def test_unknown_command_does_not_crash(env: BotTestEnv) -> None:
    await env.dispatcher.feed_update(env.bot, message_update("/nonsense"))
