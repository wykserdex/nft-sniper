"""Кандидаты алертов: что notifier получает от valuator.

``ListingScore`` — плоская сводка оцененного листинга (ансамбль + риск +
признаки), которую notifier матчит с подписчиками. ``Subscriber`` —
пользователь с политикой алертов. ``AlertCandidate`` — листинг, прошедший
матчинг, готовый к рендеру и доставке.

Риск здесь — плоские значения (``risk_value``, ``risk_flags``), а не
``RiskScore``: alerts не зависит от risk-контекста (как ``Collection.
risk_score`` хранит Decimal, а не объект).
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from nftsniper.contexts.alerts.domain.alert import AlertPolicy
from nftsniper.contexts.sources.domain.listing import Listing
from nftsniper.contexts.valuation.domain.discount import Discount
from nftsniper.shared.domain.base import ValueObject
from nftsniper.shared.money import TONAmount


@dataclass(frozen=True, slots=True)
class Subscriber(ValueObject):
    """Пользователь, чьи настройки матчатся с листингами."""

    user_id: str
    policy: AlertPolicy
    language: str = "ru"
    paused: bool = False


@dataclass(frozen=True, slots=True)
class ListingScore(ValueObject):
    """Сводка оцененного листинга для notifier (ТЗ §6: ListingScored + риск).

    Поля собраны из ``ListingScored`` (fair price, confidence, discount),
    признаков коллекции (floor, медиана, ликвидность, объём) и risk-скрининга.
    """

    listing: Listing
    fair_price: TONAmount
    confidence: Decimal
    discount: Discount
    liquidity: Decimal  # нормированный скор 0..1 (матчинг с min_liquidity)
    risk_value: Decimal  # 0..1 (RiskScore.value)
    floor_p5: TONAmount
    median_7d: TONAmount
    sales_per_day: Decimal = Decimal("0")  # сырое, продаж/день (для рендера)
    risk_flags: tuple[str, ...] = ()
    sales_7d: int = 0
    floor_24h_change: Decimal = Decimal("0")
    collection_name: str = ""
    valuation_id: str = ""
    getgems_url: str = ""


@dataclass(frozen=True, slots=True)
class AlertCandidate(ValueObject):
    """Листинг, прошедший матчинг: всё для рендера и доставки алерта."""

    alert_id: str
    user_id: str
    language: str
    listing_id: str
    dedup_key: str
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
    floor_24h_change: Decimal
    liquidity_spd: Decimal
    listing_age_seconds: int
    priority: Decimal
    rarity_rank: Decimal | None = None
    risk_flags: tuple[str, ...] = ()
    valuation_id: str = ""
    getgems_url: str = ""
