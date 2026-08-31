"""RebuildStats: пересчёт статистики коллекции и сохранение в фич-стор.

Зависит только от портов (репозитории sources + FeatureStorePort) — доменную
математику берёт из ``stats.py``. Пересчитывается как «с нуля», так и
инкрементально: если в фич-сторе есть предыдущий снимок, дневная история floor
продлевается (снимок того же дня заменяется, не плодится).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal

from nftsniper.contexts.sources.application.clock import utcnow
from nftsniper.contexts.sources.ports.repositories import ListingRepository, SaleRepository
from nftsniper.contexts.valuation.application.stats import compute_collection_stats
from nftsniper.contexts.valuation.domain.fair_price import CollectionFeatures
from nftsniper.contexts.valuation.domain.liquidity import LiquidityScore
from nftsniper.contexts.valuation.ports import FeatureStorePort

STATS_WINDOW = timedelta(days=7)  # окно продаж для статистики


@dataclass(frozen=True, slots=True)
class RebuildStatsResult:
    collection_id: str
    features: CollectionFeatures
    liquidity: LiquidityScore
    incremental: bool  # использовался ли предыдущий снимок для истории floor


class RebuildStats:
    """Пересчёт price_stats коллекции: floor P5, медиана с затуханием,
    объёмы, sales_per_day, ликвидность, momentum 24h/7d (ТЗ §7)."""

    def __init__(
        self,
        listings: ListingRepository,
        sales: SaleRepository,
        features: FeatureStorePort,
        *,
        clock: Callable[[], datetime] = utcnow,
        liquidity_target_per_day: Decimal = Decimal("5"),
    ) -> None:
        self._listings = listings
        self._sales = sales
        self._features = features
        self._clock = clock
        self._liquidity_target = liquidity_target_per_day

    async def run(self, collection_id: str) -> RebuildStatsResult:
        now = self._clock()
        active = await self._listings.list_active(collection_id=collection_id)
        since = now - STATS_WINDOW
        sales = await self._sales.list_by_collection(collection_id, since)

        previous = await self._features.load(collection_id)
        stats = compute_collection_stats(
            collection_id=collection_id,
            active_listings=active,
            sales=sales,
            now=now,
            previous=previous,
            liquidity_target_per_day=self._liquidity_target,
        )
        await self._features.save(stats.features)
        return RebuildStatsResult(
            collection_id=collection_id,
            features=stats.features,
            liquidity=stats.liquidity,
            incremental=previous is not None,
        )
