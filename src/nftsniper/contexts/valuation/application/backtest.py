"""Бэктест оценки: медианная ошибка fair price против фактических продаж.

Критерий готовности  (ТЗ §7): «на историческом бэктесте медианная
ошибка ниже согласованного порога и оценка всегда объяснима».

Подход — walk-forward по продажам без look-ahead: для каждой продажи
используются только продажи строго раньше неё (плюс стабильный пул активных
листингов как floor-база). Ошибка — относительное отклонение
``|fair - actual| / actual`` (MAPE на сделку); итог — медиана ошибок.

``BacktestReport`` содержит медиану, среднее, массив ошибок, флаг
объяснимости (у каждой оценки непустое explanation) и вердикт по порогу.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal

from nftsniper.contexts.sources.domain.item import Item
from nftsniper.contexts.sources.domain.listing import Listing, ListingStatus
from nftsniper.contexts.sources.domain.marketplace import Marketplace
from nftsniper.contexts.sources.domain.sale import SaleEvent
from nftsniper.contexts.valuation.application.stats import compute_collection_stats
from nftsniper.contexts.valuation.domain.fair_price import FairPriceEstimate
from nftsniper.contexts.valuation.ports import PriceModelPort

DEFAULT_ERROR_THRESHOLD = Decimal("0.40")  # медианная ошибка (MAPE) ≤ 40%


@dataclass(frozen=True, slots=True)
class BacktestReport:
    """Итог бэктеста: медианная ошибка и вердикт по порогу."""

    checked: int
    median_error: Decimal
    mean_error: Decimal
    errors: tuple[Decimal, ...]
    all_explainable: bool
    threshold: Decimal

    @property
    def passed(self) -> bool:
        return self.checked > 0 and self.median_error <= self.threshold and self.all_explainable


def _relative_error(estimate: FairPriceEstimate, actual_price: Decimal) -> Decimal:
    return abs(estimate.value.ton - actual_price) / actual_price


def median_error(errors: Sequence[Decimal]) -> Decimal:
    """Медиана (nearest-rank) списка ошибок; пусто → 0."""
    if not errors:
        return Decimal(0)
    ordered = sorted(errors)
    return ordered[len(ordered) // 2]


async def run_backtest(
    *,
    model: PriceModelPort,
    sales: Sequence[SaleEvent],
    active_listings: Sequence[Listing],
    item_by_id: Mapping[str, Item],
    threshold: Decimal = DEFAULT_ERROR_THRESHOLD,
) -> BacktestReport:
    """Walk-forward бэктест: оценка vs фактические продажи (без look-ahead).

    ``sales`` — хронологические (oldest-first); ``active_listings`` — пул
    листингов, служащий floor-базой (в реальном бэктесте — снапшот на момент
    продажи; здесь — константа, приближение задокументировано).
    """
    errors: list[Decimal] = []
    all_explainable = True
    collection_id = sales[0].collection_id if sales else ""

    for sale in sorted(sales, key=lambda item: item.sold_at):
        prior = [s for s in sales if s.sold_at < sale.sold_at]
        if not prior:
            continue  # первой продаже не с чем сравнивать — пропускаем
        features = compute_collection_stats(
            collection_id=collection_id,
            active_listings=active_listings,
            sales=prior,
            now=sale.sold_at,
        ).features

        item = item_by_id.get(sale.item_id)
        if item is None:
            continue
        listing = Listing(
            id=f"backtest:{sale.id}",
            external_id=sale.id,
            marketplace=Marketplace.GETGEMS,
            item=item,
            price=sale.price,
            seller=sale.seller,
            listed_at=sale.sold_at,
            status=ListingStatus.ACTIVE,
        )
        estimate = await model.estimate(listing, features)
        errors.append(_relative_error(estimate, sale.price.ton))
        all_explainable = all_explainable and bool(estimate.explanation)

    return BacktestReport(
        checked=len(errors),
        median_error=median_error(errors),
        mean_error=sum(errors, start=Decimal(0)) / Decimal(len(errors)) if errors else Decimal(0),
        errors=tuple(errors),
        all_explainable=all_explainable,
        threshold=threshold,
    )
