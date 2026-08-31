"""Рендер алерта и решений в Telegram (ТЗ §1).

Чистые функции: на входе доменные значения (TONAmount/Decimal, без float),
на выходе — ``AlertMessage`` (текст + кнопки) из alerts-контекста. Формат
сообщения повторяет пример алерта из ТЗ §1.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal

from nftsniper.contexts.alerts.domain.alert import AlertButton, AlertMessage
from nftsniper.entrypoints.bot.i18n import _Strings, get_strings
from nftsniper.shared.money import TONAmount

# Действия-кнопки (ТЗ §1): callback_data короче 64 байт — только alert_id.
ACTION_TAKEN = "taken"
ACTION_SKIPPED = "skipped"
ACTION_WATCH = "watch"
ACTION_MUTED = "muted"

DECISION_ACTIONS = (ACTION_TAKEN, ACTION_SKIPPED, ACTION_WATCH, ACTION_MUTED)

# Константы времени и кодеков (ruff: без магических чисел).
_SECONDS_PER_MINUTE = 60
_SECONDS_PER_HOUR = 3600
_SECONDS_PER_DAY = 86400
_CALLBACK_PARTS = 3


@dataclass(frozen=True, slots=True)
class AlertView:
    """Всё, что нужно боту для рендера алерта и обработки решения."""

    alert_id: str
    listing_id: str
    item_id: str
    item_name: str
    collection_id: str
    collection_name: str
    price: TONAmount
    fair_price: TONAmount
    discount: Decimal  # доля, например 0.42
    confidence: Decimal  # 0..1
    floor_p5: TONAmount
    median_7d: TONAmount
    sales_7d: int
    floor_24h_change: Decimal  # относительное, например -0.03
    liquidity_spd: Decimal  # продаж/день
    listing_age_seconds: int
    rarity_rank: Decimal | None = None  # перцентиль 0..1, меньше = реже
    risk_flags: tuple[str, ...] = ()
    price_usd: str | None = None
    getgems_url: str = ""


def _fmt_pct(value: Decimal) -> str:
    """Доля → процентная строка: 0.42 → "42%", -0.03 → "-3%"."""
    percent = (value * Decimal(100)).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return f"{int(percent)}%"


def _fmt_confidence_label(value: Decimal, strings: _Strings) -> str:
    if value >= Decimal("0.7"):
        return strings.confidence_high
    if value >= Decimal("0.5"):
        return strings.confidence_medium
    return strings.confidence_low


def _fmt_age(seconds: int, strings: _Strings) -> str:
    if seconds < _SECONDS_PER_MINUTE:
        return strings.age_sec.format(n=seconds)
    if seconds < _SECONDS_PER_HOUR:
        return strings.age_min.format(n=seconds // _SECONDS_PER_MINUTE)
    if seconds < _SECONDS_PER_DAY:
        return strings.age_hour.format(n=seconds // _SECONDS_PER_HOUR)
    return strings.age_day.format(n=seconds // _SECONDS_PER_DAY)


def render_alert(view: AlertView, lang: str = "ru") -> AlertMessage:
    """Собрать сообщение алерта (текст HTML + кнопки) из AlertView."""
    s = get_strings(lang)
    discount_pct = _fmt_pct(view.discount)
    lines: list[str] = [f"<b>{s.deal_title.format(discount=discount_pct)}</b>", ""]

    lines.append(f"<b>{_escape(view.item_name)}</b>")
    lines.append(s.line_collection.format(name=_escape(view.collection_name)))
    if view.price_usd:
        lines.append(s.line_price.format(price=view.price.formatted, usd=view.price_usd))
    else:
        lines.append(s.line_price_no_usd.format(price=view.price.formatted))
    lines.append(s.line_fair.format(fair=view.fair_price.formatted))
    lines.append(s.line_discount.format(discount=_discount_sign(discount_pct)))
    lines.append("")
    lines.append(
        s.line_floor.format(
            floor=view.floor_p5.formatted,
            change=_fmt_pct(view.floor_24h_change),
        )
    )
    lines.append(s.line_median.format(median=view.median_7d.formatted, sales=view.sales_7d))
    if view.rarity_rank is not None:
        lines.append(s.line_rarity.format(pct=_fmt_pct(view.rarity_rank)))
    lines.append(s.line_liquidity.format(spd=view.liquidity_spd))
    lines.append(s.line_age.format(age=_fmt_age(view.listing_age_seconds, s)))
    lines.append("")
    lines.append(
        s.line_confidence.format(
            confidence=view.confidence,
            label=_fmt_confidence_label(view.confidence, s),
        )
    )
    for flag in view.risk_flags:
        lines.append(s.flag_warning.format(flag=_escape(flag)))

    buttons = [
        AlertButton(text=s.btn_take, callback_data=_decision_cb(ACTION_TAKEN, view.alert_id)),
        AlertButton(text=s.btn_skip, callback_data=_decision_cb(ACTION_SKIPPED, view.alert_id)),
        AlertButton(text=s.btn_watch, callback_data=_decision_cb(ACTION_WATCH, view.alert_id)),
        AlertButton(text=s.btn_mute, callback_data=_decision_cb(ACTION_MUTED, view.alert_id)),
    ]
    if view.getgems_url:
        buttons.append(AlertButton(text=s.btn_open, url=view.getgems_url))

    return AlertMessage(text="\n".join(lines), buttons=tuple(buttons))


def render_decision_ack(view: AlertView, action: str, lang: str = "ru") -> AlertMessage:
    """Текст после решения (заменяет исходное сообщение, ТЗ §6)."""
    s = get_strings(lang)
    if action == ACTION_TAKEN:
        text = s.decided_taken.format(link=view.getgems_url or view.item_id)
    elif action == ACTION_SKIPPED:
        text = s.decided_skipped
    elif action == ACTION_WATCH:
        text = s.decided_watch
    elif action == ACTION_MUTED:
        text = s.decided_muted
    else:
        text = s.decided_unknown
    return AlertMessage(text=text)


def render_decision_popup(action: str, lang: str = "ru") -> str:
    """Текст всплывашки answer_callback_query."""
    s = get_strings(lang)
    if action == ACTION_TAKEN:
        return s.take_link_hint
    return ""


# ── callback_data кодек ─────────────────────────────────────────────────


def _decision_cb(action: str, alert_id: str) -> str:
    return f"dec:{action}:{alert_id}"


def parse_decision_cb(data: str) -> tuple[str, str] | None:
    """``dec:action:alert_id`` → (action, alert_id) или None."""
    parts = data.split(":")
    if len(parts) != _CALLBACK_PARTS or parts[0] != "dec":
        return None
    action, alert_id = parts[1], parts[2]
    if action not in DECISION_ACTIONS or not alert_id:
        return None
    return action, alert_id


def _discount_sign(discount_pct: str) -> str:
    """Дискаунт в тексте как в ТЗ: скидка → "-42%" (минус)."""
    return f"-{discount_pct}"


def _escape(text: str) -> str:
    """Экранирование HTML в пользовательских строках (имена/флаги)."""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def listing_age_seconds(listed_at: datetime, now: datetime | None = None) -> int:
    """Возраст листинга в секундах (для «Возраст листинга: 11 сек»)."""
    effective_now = now if now is not None else datetime.now(UTC)
    if listed_at.tzinfo is None:
        listed_at = listed_at.replace(tzinfo=UTC)
    delta = effective_now - listed_at
    total = delta.days * _SECONDS_PER_DAY + delta.seconds
    return max(0, total)
