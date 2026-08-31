"""Рендер алерта: формат ТЗ §1, кнопки, кодек callback, экранирование."""

from datetime import UTC, datetime
from decimal import Decimal

from nftsniper.contexts.alerts.domain.alert import AlertButton
from nftsniper.entrypoints.bot.render import (
    AlertView,
    listing_age_seconds,
    parse_decision_cb,
    render_alert,
)
from nftsniper.shared.money import TONAmount

D = Decimal


def make_view(**overrides: object) -> AlertView:
    base: dict[str, object] = {
        "alert_id": "al-1",
        "listing_id": "lg-1",
        "item_id": "EQItem888",
        "item_name": "Anonymous Telegram Number #888",
        "collection_id": "EQColl",
        "collection_name": "Anonymous Numbers",
        "price": TONAmount.from_ton(120),
        "fair_price": TONAmount.from_ton(207),
        "discount": D("0.42"),
        "confidence": D("0.78"),
        "floor_p5": TONAmount.from_ton(195),
        "median_7d": TONAmount.from_ton(214),
        "sales_7d": 18,
        "floor_24h_change": D("-0.03"),
        "liquidity_spd": D("2.4"),
        "listing_age_seconds": 11,
        "rarity_rank": D("0.08"),
        "risk_flags": ("продавец создан 2 дня назад",),
        "price_usd": "$580",
        "getgems_url": "https://getgems.io/nft/EQItem888",
    }
    base.update(overrides)
    return AlertView(**base)  # type: ignore[arg-type]


def test_render_alert_matches_tz_example() -> None:
    message = render_alert(make_view(), lang="ru")
    assert "🔥 Deal 42%" in message.text
    assert "Anonymous Telegram Number #888" in message.text
    assert "Коллекция: Anonymous Numbers" in message.text
    assert "Цена: 120 TON ($580)" in message.text
    assert "Fair price: 207 TON" in message.text
    assert "Дискаунт: -42%" in message.text
    assert "Floor: 195 TON (24h: -3%)" in message.text
    assert "Median 7d: 214 TON (18 продаж)" in message.text
    assert "Rarity: топ 8% по коллекции" in message.text
    assert "Ликвидность: 2.4 продаж/день" in message.text
    assert "Возраст листинга: 11 сек" in message.text
    assert "Уверенность оценки: 0.78 (высокая)" in message.text
    assert "⚠️ Флаг: продавец создан 2 дня назад" in message.text


def test_render_alert_english() -> None:
    message = render_alert(make_view(), lang="en")
    assert "🔥 Deal 42%" in message.text
    assert "Collection: Anonymous Numbers" in message.text
    assert "Fair price: 207 TON" in message.text
    assert "confidence: 0.78 (high)" in message.text


def test_render_alert_buttons() -> None:
    message = render_alert(make_view())
    labels = [button.text for button in message.buttons]
    assert labels == [
        "✅ Взять",
        "❌ Скип",
        "🔔 Следить",
        "🔇 Мьют коллекции",
        "🔗 Открыть на GetGems",
    ]
    decision_buttons = message.buttons[:4]
    assert all(isinstance(b, AlertButton) and b.callback_data for b in decision_buttons)
    link = message.buttons[4]
    assert link.url == "https://getgems.io/nft/EQItem888"


def test_render_alert_without_usd_and_rarity() -> None:
    message = render_alert(
        make_view(price_usd=None, rarity_rank=None, risk_flags=(), getgems_url="")
    )
    assert "Цена: 120 TON" in message.text
    assert "Rarity" not in message.text
    assert len(message.buttons) == 4  # без ссылки на GetGems


def test_html_escaping() -> None:
    message = render_alert(make_view(item_name="<b>x</b> & <i>y</i>"))
    assert "<b>x</b>" not in message.text
    assert "&lt;b&gt;x&lt;/b&gt;" in message.text


def test_parse_decision_cb() -> None:
    assert parse_decision_cb("dec:taken:al-1") == ("taken", "al-1")
    assert parse_decision_cb("dec:skipped:al-2") == ("skipped", "al-2")
    assert parse_decision_cb("dec:bogus:al-1") is None
    assert parse_decision_cb("dec:taken") is None
    assert parse_decision_cb("set:lang") is None
    assert parse_decision_cb("") is None


def test_listing_age_seconds() -> None:
    now = datetime(2026, 8, 31, 12, 0, 11, tzinfo=UTC)
    listed = datetime(2026, 8, 31, 12, 0, 0, tzinfo=UTC)
    assert listing_age_seconds(listed, now=now) == 11
    assert listing_age_seconds(listed, now=listed) == 0
    assert listing_age_seconds(now, now=listed) == 0  # не бывает отрицательным
