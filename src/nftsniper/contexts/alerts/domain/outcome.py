"""Исход алерта: что стало с листингом через 1h/24h/7d (ТЗ §5, §6).

``Outcome`` фиксирует цены по окнам трекинга и факт продажи; на нём
считаются precision (подтвердился ли fair price) и контрфактуал
«что было бы, если бы вы взяли все алерты».
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from decimal import Decimal
from enum import StrEnum

from nftsniper.shared.domain.base import Entity
from nftsniper.shared.money import TONAmount


class OutcomeWindow(StrEnum):
    """Окно трекинга исхода (ТЗ §6: 1h / 24h / 7d)."""

    ONE_HOUR = "1h"
    TWENTY_FOUR_HOURS = "24h"
    SEVEN_DAYS = "7d"


@dataclass(frozen=True, slots=True)
class Outcome(Entity):
    """Исход алерта (таблица ``outcomes``, ТЗ §5).

    Цены заполняются трекером по окнам; ``sold_*`` — когда листинг продан.
    ``alert_price``/``fair_price``/``discount`` фиксируются в момент первого
    снимка — база для precision и контрфактуала.
    """

    id: str
    alert_id: str
    user_id: str
    listing_id: str
    alert_price: TONAmount
    fair_price: TONAmount
    discount: Decimal
    computed_at: datetime
    price_after_1h: TONAmount | None = None
    price_after_24h: TONAmount | None = None
    price_after_7d: TONAmount | None = None
    sold_at: datetime | None = None
    sold_price: TONAmount | None = None

    def __post_init__(self) -> None:
        if self.fair_price <= TONAmount.zero():
            msg = "fair_price должен быть положительным"
            raise ValueError(msg)

    # ── снимки ───────────────────────────────────────────────────────────

    def apply_snapshot(self, *, window: OutcomeWindow, price: TONAmount, at: datetime) -> Outcome:
        """Записать цену листинга в окно ``window``."""
        if window is OutcomeWindow.ONE_HOUR:
            return replace(self, price_after_1h=price, computed_at=at)
        if window is OutcomeWindow.TWENTY_FOUR_HOURS:
            return replace(self, price_after_24h=price, computed_at=at)
        return replace(self, price_after_7d=price, computed_at=at)

    def mark_sold(self, *, sold_at: datetime, sold_price: TONAmount, at: datetime) -> Outcome:
        """Зафиксировать продажу листинга (реализованный исход)."""
        return replace(self, sold_at=sold_at, sold_price=sold_price, computed_at=at)

    # ── оценка ───────────────────────────────────────────────────────────

    @property
    def has_data(self) -> bool:
        """Есть ли хоть один снимок цены или продажа."""
        return (
            self.price_after_1h is not None
            or self.price_after_24h is not None
            or self.price_after_7d is not None
            or self.sold_price is not None
        )

    def final_price(self) -> TONAmount:
        """Последняя известная цена: продажа > 24h > 7d > 1h > цена алерта."""
        if self.sold_price is not None:
            return self.sold_price
        for price in (self.price_after_24h, self.price_after_7d, self.price_after_1h):
            if price is not None:
                return price
        return self.alert_price

    def confirmed_24h(self, *, tolerance: Decimal = Decimal("0")) -> bool | None:
        """Fair price подтвердился? Рынок достиг ``fair × (1 − tolerance)``.

        Продажа по цене ≥ цели считается подтверждением. ``None`` = нет данных.
        """
        target = self.fair_price.scale(Decimal(1) - tolerance)
        if self.price_after_24h is not None:
            return self.price_after_24h >= target
        if self.sold_price is not None:
            return self.sold_price >= target
        return None

    def is_winning(self) -> bool | None:
        """Сделка оказалась реальной (цена выросла относительно цены алерта)?

        ``None`` = нет данных. Строгое ``>``: цена без движения — не выигрыш.
        """
        if not self.has_data:
            return None
        return self.final_price() > self.alert_price
