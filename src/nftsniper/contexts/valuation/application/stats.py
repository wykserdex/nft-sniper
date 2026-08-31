"""Статистика коллекций: чистая математика на Decimal, без float.

Все функции детерминированы — это и эталонный расчёт для тестов, и
рантайм-пересчёт. Конвенции (ТЗ §4, §5):

- ``floor_p5`` — устойчивый floor: перцентиль P5 активных листингов
  (nearest-rank), а не минимум — один мусорный листинг не роняет floor;
- ``median_7d`` — взвешенная медиана продаж за 7 дней с временным затуханием
  (полураспад 7 дней): свежие продажи весят больше;
- ``volume_24h`` — сумма цен продаж за 24 часа;
- ``sales_per_day`` — продажи за 7 дней / 7;
- momentum — относительное изменение floor за 24h/7d по дневной истории
  (``floor_history``, новые значения в конце).

Производительность: P5 и медиана — это сортировки O(n log n); пересчёт
коллекции из 10k предметов укладывается в десятки миллисекунд (см. perf-тест).
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal

from nftsniper.contexts.sources.domain.listing import Listing
from nftsniper.contexts.sources.domain.sale import SaleEvent
from nftsniper.contexts.valuation.domain.fair_price import CollectionFeatures
from nftsniper.contexts.valuation.domain.liquidity import LiquidityScore
from nftsniper.shared.money import TONAmount

SEVEN_DAYS = timedelta(days=7)
ONE_DAY = timedelta(days=1)
DEFAULT_HALF_LIFE_DAYS = Decimal("7")
DEFAULT_LIQUIDITY_TARGET = Decimal("5")  # продаж/день, при котором скор = 1
DEFAULT_HISTORY_LEN = 90  # дней истории floor для momentum
_SECONDS_PER_DAY = Decimal(86400)


class InsufficientDataError(ValueError):
    """Недостаточно данных для расчёта статистики коллекции."""


def _timedelta_days(td: timedelta) -> Decimal:
    """timedelta → Decimal дней без float (точность до микросекунды)."""
    return (
        Decimal(td.days)
        + Decimal(td.seconds) / _SECONDS_PER_DAY
        + Decimal(td.microseconds) / (_SECONDS_PER_DAY * Decimal(1_000_000))
    )


# ── перцентили и медианы ────────────────────────────────────────────────


def percentile_nearest_rank(prices: Sequence[TONAmount], p: Decimal) -> TONAmount:
    """Nearest-rank перцентиль: элемент с рангом ``ceil(p * n / 100)``.

    ``p`` — в [0, 100]. Сортировка внутри (копия входного списка).
    """
    if not prices:
        msg = "нельзя считать перцентиль на пустой выборке"
        raise InsufficientDataError(msg)
    if not (Decimal(0) <= p <= Decimal(100)):
        msg = f"перцентиль должен быть в [0, 100], получено {p}"
        raise ValueError(msg)
    ordered = sorted(prices)
    rank = math.ceil(p * Decimal(len(ordered)) / Decimal(100))
    return ordered[max(0, rank - 1)]


def floor_p5(active_listings: Sequence[Listing]) -> TONAmount:
    """Устойчивый floor коллекции: P5 цен активных листингов (ТЗ §4)."""
    prices = [listing.price for listing in active_listings if listing.is_active]
    if not prices:
        msg = "floor нельзя посчитать без активных листингов"
        raise InsufficientDataError(msg)
    return percentile_nearest_rank(prices, Decimal("5"))


def decay_weight(
    age_days: Decimal,
    *,
    half_life_days: Decimal = DEFAULT_HALF_LIFE_DAYS,
) -> Decimal:
    """Вес продажи возрастом ``age_days``: ``0.5 ** (age / half_life)``."""
    if age_days < 0:
        msg = "возраст не может быть отрицательным"
        raise ValueError(msg)
    if half_life_days <= 0:
        msg = "полураспад должен быть положительным"
        raise ValueError(msg)
    return Decimal("0.5") ** (age_days / half_life_days)


@dataclass(frozen=True, slots=True)
class WeightedPrice:
    """Цена и её вес (для взвешенной медианы)."""

    price: TONAmount
    weight: Decimal


def time_decayed_median(points: Sequence[WeightedPrice]) -> TONAmount:
    """Взвешенная медиана: первая цена, где кумулятивный вес ≥ 50% суммы."""
    if not points:
        msg = "нельзя считать медиану на пустой выборке"
        raise InsufficientDataError(msg)
    ordered = sorted(points, key=lambda point: point.price)
    total = sum((point.weight for point in ordered), start=Decimal(0))
    if total <= 0:
        msg = "суммарный вес должен быть положительным"
        raise InsufficientDataError(msg)
    target = total / Decimal(2)
    cumulative = Decimal(0)
    for point in ordered:
        cumulative += point.weight
        if cumulative >= target:
            return point.price
    return ordered[-1].price


def sales_in_window(
    sales: Sequence[SaleEvent],
    *,
    now: datetime,
    window: timedelta,
) -> Sequence[SaleEvent]:
    """Продажи с ``sold_at`` в ``[now - window, now]``."""
    cutoff = now - window
    return [sale for sale in sales if cutoff <= sale.sold_at <= now]


def volume(sales: Sequence[SaleEvent]) -> TONAmount:
    """Сумма цен продаж."""
    return sum((sale.price for sale in sales), start=TONAmount.zero())


def sales_per_day(
    sales: Sequence[SaleEvent],
    *,
    now: datetime,
    window: timedelta = SEVEN_DAYS,
) -> Decimal:
    """Среднее число продаж в день за окно (продажи / дней в окне)."""
    count = len(sales_in_window(sales, now=now, window=window))
    days = _timedelta_days(window)
    return Decimal(count) / days


def decayed_sales_median(
    sales: Sequence[SaleEvent],
    *,
    now: datetime,
    window: timedelta = SEVEN_DAYS,
    half_life_days: Decimal = DEFAULT_HALF_LIFE_DAYS,
) -> TONAmount:
    """Медиана продаж за окно с временным затуханием (полураспад 7 дней)."""
    points: list[WeightedPrice] = []
    cutoff = now - window
    for sale in sales:
        if cutoff <= sale.sold_at <= now:
            age = _timedelta_days(now - sale.sold_at)
            points.append(
                WeightedPrice(
                    price=sale.price,
                    weight=decay_weight(age, half_life_days=half_life_days),
                )
            )
    return time_decayed_median(points)


# ── momentum и история floor ────────────────────────────────────────────


def floor_change(history: Sequence[Decimal], *, steps_back: int) -> Decimal | None:
    """Относительное изменение floor: ``(last - value) / value``.

    ``history`` — дневные снимки floor, новые в конце (последний = текущий);
    ``steps_back`` = 1 → изменение за 24h, 7 → за 7 дней. ``None``, если
    истории не хватает или базовое значение нулевое.
    """
    if steps_back < 1:
        msg = "steps_back должен быть >= 1"
        raise ValueError(msg)
    if len(history) < steps_back + 1:
        return None
    past = history[-steps_back - 1]
    current = history[-1]
    if past <= 0:
        return None
    return (current - past) / past


def append_floor_snapshot(
    history: tuple[Decimal, ...],
    floor: Decimal,
    *,
    same_day_as_previous: bool,
    max_len: int = DEFAULT_HISTORY_LEN,
) -> tuple[Decimal, ...]:
    """Добавить сегодняшний снимок floor; снимок того же дня — заменяется."""
    merged = (*history[:-1], floor) if (same_day_as_previous and history) else (*history, floor)
    if len(merged) > max_len:
        merged = merged[-max_len:]
    return merged


# ── ликвидность ─────────────────────────────────────────────────────────


def normalize_liquidity(
    sales_per_day: Decimal,
    *,
    target_per_day: Decimal = DEFAULT_LIQUIDITY_TARGET,
) -> Decimal:
    """Нормированный скор ликвидности 0..1: ``min(1, spd / target)``."""
    if target_per_day <= 0:
        msg = "target_per_day должен быть положительным"
        raise ValueError(msg)
    if sales_per_day < 0:
        msg = "sales_per_day не может быть отрицательным"
        raise ValueError(msg)
    return min(sales_per_day / target_per_day, Decimal(1))


# ── итоговый расчёт ─────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class CollectionStats:
    """Итог пересчёта: признаки коллекции + нормированная ликвидность."""

    features: CollectionFeatures
    liquidity: LiquidityScore


def compute_collection_stats(
    *,
    collection_id: str,
    active_listings: Sequence[Listing],
    sales: Sequence[SaleEvent],
    now: datetime,
    previous: CollectionFeatures | None = None,
    liquidity_target_per_day: Decimal = DEFAULT_LIQUIDITY_TARGET,
    max_history_len: int = DEFAULT_HISTORY_LEN,
) -> CollectionStats:
    """Пересчёт статистики коллекции из листингов и продаж.

    Требует хотя бы один активный листинг (иначе floor не определить).
    Нет продаж за 7 дней — ``median_7d`` откатывается на ``floor_p5``
    (единственный ценовой сигнал), а ликвидность = 0: такие коллекции
    отсеются минимумом ликвидности в алертах (ТЗ §4).
    """
    floor = floor_p5(active_listings)

    window_sales = sales_in_window(sales, now=now, window=SEVEN_DAYS)
    try:
        median = decayed_sales_median(window_sales, now=now, window=SEVEN_DAYS)
    except InsufficientDataError:
        median = floor  # нет продаж — откат на floor

    spd = sales_per_day(window_sales, now=now, window=SEVEN_DAYS)
    volume_24h = volume(sales_in_window(sales, now=now, window=ONE_DAY))

    same_day = previous is not None and previous.as_of.date() == now.date()
    history = append_floor_snapshot(
        previous.floor_history if previous is not None else (),
        floor.ton,
        same_day_as_previous=same_day,
        max_len=max_history_len,
    )
    change_24h = floor_change(history, steps_back=1)
    change_7d = floor_change(history, steps_back=7)

    features = CollectionFeatures(
        collection_id=collection_id,
        floor_p5=floor,
        median_7d=median,
        volume_24h=volume_24h,
        sales_per_day=spd,
        listings_count=len([listing for listing in active_listings if listing.is_active]),
        floor_24h_change=change_24h if change_24h is not None else Decimal(0),
        floor_7d_change=change_7d if change_7d is not None else Decimal(0),
        as_of=now,
        floor_history=history,
    )
    liquidity = LiquidityScore(
        value=normalize_liquidity(spd, target_per_day=liquidity_target_per_day),
        sales_per_day=spd,
        basis=f"min(1, {spd}/{liquidity_target_per_day}) за 7 дней",
    )
    return CollectionStats(features=features, liquidity=liquidity)
