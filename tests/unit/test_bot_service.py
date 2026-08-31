"""BotService: команды, FSM-валидация, решения, статистика."""

from datetime import datetime
from decimal import Decimal

from nftsniper.entrypoints.bot.adapters import (
    InMemoryAlertRegistry,
    InMemoryDecisionStore,
    InMemoryUserSettingsStore,
    InMemoryWatchlistStore,
)
from nftsniper.entrypoints.bot.render import AlertView
from nftsniper.entrypoints.bot.service import BotService
from nftsniper.shared.money import TONAmount

D = Decimal


def make_view(alert_id: str = "al-1") -> AlertView:
    return AlertView(
        alert_id=alert_id,
        listing_id="lg-1",
        item_id="EQItem888",
        item_name="Number #888",
        collection_id="EQColl",
        collection_name="Anonymous Numbers",
        price=TONAmount.from_ton(120),
        fair_price=TONAmount.from_ton(207),
        discount=D("0.42"),
        confidence=D("0.78"),
        floor_p5=TONAmount.from_ton(195),
        median_7d=TONAmount.from_ton(214),
        sales_7d=18,
        floor_24h_change=D("-0.03"),
        liquidity_spd=D("2.4"),
        listing_age_seconds=11,
        getgems_url="https://getgems.io/nft/EQItem888",
    )


def make_service() -> tuple[
    BotService,
    InMemoryUserSettingsStore,
    InMemoryWatchlistStore,
    InMemoryDecisionStore,
    InMemoryAlertRegistry,
]:
    settings = InMemoryUserSettingsStore()
    watchlist = InMemoryWatchlistStore()
    decisions = InMemoryDecisionStore()
    registry = InMemoryAlertRegistry()
    service = BotService(
        settings=settings,
        watchlist=watchlist,
        decisions=decisions,
        registry=registry,
        clock=datetime,
    )
    return service, settings, watchlist, decisions, registry


async def test_start_text_language() -> None:
    service, *_ = make_service()
    assert "Привет" in await service.start_text("u1", None)
    assert "Hi!" in await service.start_text("u2", "en")


async def test_settings_prompt_lists_values() -> None:
    service, *_ = make_service()
    await service.apply_setting("u1", "min_discount", "30")
    text = await service.settings_prompt("u1")
    assert "30%" in text
    assert "0.5" in text  # min_confidence по умолчанию


async def test_apply_setting_invalid_keeps_old() -> None:
    service, settings, *_ = make_service()
    ok, text = await service.apply_setting("u1", "min_discount", "999")
    assert ok is False
    assert "Не получилось" in text
    stored = await settings.get("u1")
    assert stored is not None
    assert stored.min_discount == D("0.25")  # старое значение не тронуто


async def test_toggle_language() -> None:
    service, settings, *_ = make_service()
    await service.toggle_language("u1")
    stored = await settings.get("u1")
    assert stored is not None
    assert stored.language == "en"


async def test_decision_taken_gives_link_and_records() -> None:
    service, _, _, decisions, _ = make_service()
    await service.register_alert(make_view())

    result = await service.handle_decision("u1", "taken", "al-1", latency_ms=123)

    assert "https://getgems.io/nft/EQItem888" in result.edited.text
    assert decisions.saved[0].action == "taken"
    assert decisions.saved[0].latency_ms == 123
    assert decisions.saved[0].alert_id == "al-1"


async def test_decision_watch_adds_to_watchlist() -> None:
    service, _, watchlist, _, _ = make_service()
    await service.register_alert(make_view())

    await service.handle_decision("u1", "watch", "al-1", latency_ms=0)

    assert await watchlist.list("u1") == ("EQItem888",)


async def test_decision_muted_mutes_collection() -> None:
    service, settings, *_ = make_service()
    await service.register_alert(make_view())

    await service.handle_decision("u1", "muted", "al-1", latency_ms=0)

    stored = await settings.get("u1")
    assert stored is not None
    assert stored.is_muted("EQColl")


async def test_decision_unknown_action_is_recorded_but_safe() -> None:
    service, *_ = make_service()
    result = await service.handle_decision("u1", "nope", "al-1", latency_ms=0)
    assert result.edited.text == "Решение записано."


async def test_stats_empty_then_counts() -> None:
    service, *_ = make_service()
    assert "пока нет" in await service.stats_text("u1")

    await service.handle_decision("u1", "taken", "al-1", latency_ms=0)
    await service.handle_decision("u1", "taken", "al-2", latency_ms=0)
    await service.handle_decision("u1", "skipped", "al-3", latency_ms=0)

    text = await service.stats_text("u1")
    assert "3" in text  # всего
    assert "2" in text  # taken


async def test_pause_and_resume() -> None:
    service, settings, *_ = make_service()
    assert "паузе" in await service.pause("u1", paused=True)
    assert "возобновлены" in await service.pause("u1", paused=False)
    assert "изменилось" in await service.pause("u1", paused=False)  # уже снята
    stored = await settings.get("u1")
    assert stored is not None
    assert stored.paused is False


async def test_register_and_lookup_alert_context() -> None:
    service, *_ = make_service()
    await service.register_alert(make_view("al-9"))
    result = await service.handle_decision("u1", "taken", "al-9", latency_ms=0)
    assert "EQItem888" in result.edited.text
