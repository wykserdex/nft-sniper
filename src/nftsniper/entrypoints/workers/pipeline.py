"""Конвейер листингов: poll → score → risk → notify.

``ListingPipeline`` склеивает готовые use cases в один проход по новым
листингам (ТЗ §6: Poller → Valuator → Notifier):

1. ``PollListings`` — новые листинги с дедупом по dedup_key;
2. признаки коллекции из фич-стора (``RebuildStats`` при отсутствии);
3. ``ScoreListing`` — fair price, confidence, discount;
4. ``ScreenListing`` — risk-скрининг (wash trading, клоны, объём, ...);
5. сборка ``ListingScore`` и ``AlertEngine.deliver`` — матчинг, дедуп,
   rate limit, приоритизация, доставка.

Это чистая оркестрация поверх портов: метрики/сеть — в entrypoint'е,
который гоняет конвейер по расписанию. Зависимость только от use cases —
тестируется end-to-end на fake'ах без I/O.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from decimal import Decimal

from nftsniper.contexts.alerts.application.engine import AlertEngine
from nftsniper.contexts.alerts.domain.candidate import ListingScore
from nftsniper.contexts.risk.application.screen import ScreenListing
from nftsniper.contexts.sources.application.poll_listings import PollListings
from nftsniper.contexts.sources.domain.collection import Collection
from nftsniper.contexts.sources.domain.listing import Listing
from nftsniper.contexts.sources.ports import MarketplacePort
from nftsniper.contexts.valuation.application.estimate_fair_price import ScoreListing
from nftsniper.contexts.valuation.application.rebuild_stats import RebuildStats
from nftsniper.contexts.valuation.application.stats import (
    DEFAULT_LIQUIDITY_TARGET,
    normalize_liquidity,
)
from nftsniper.contexts.valuation.ports import FeatureStorePort


def getgems_item_url(address: str) -> str:
    """Диплинк на предмет в GetGems (кнопка «Открыть на GetGems», ТЗ §1)."""
    return f"https://getgems.io/nft/{address}"


@dataclass(frozen=True, slots=True)
class PipelineReport:
    """Итог прохода конвейера: сколько нашлось, оценено, доставлено."""

    discovered: int
    scored: int
    risk_flagged: int
    matched: int
    delivered: int
    dropped: int
    listings: tuple[Listing, ...] = ()


def _fallback_collection(collection_id: str) -> Collection:
    """Заглушка коллекции, если источник не вернул карточку (name/royalty)."""
    return Collection(
        id=collection_id,
        name=collection_id,
        slug=collection_id.lower(),
        royalty_bps=0,
    )


class ListingPipeline:
    """Один проход конвейера по новым листингам (poller → valuator → notifier)."""

    def __init__(
        self,
        *,
        poller: PollListings,
        features: FeatureStorePort,
        rebuild: RebuildStats,
        scorer: ScoreListing,
        screen: ScreenListing,
        collections: MarketplacePort,
        engine: AlertEngine,
        liquidity_target_per_day: Decimal = DEFAULT_LIQUIDITY_TARGET,
        url_builder: Callable[[str], str] = getgems_item_url,
    ) -> None:
        self._poller = poller
        self._features = features
        self._rebuild = rebuild
        self._scorer = scorer
        self._screen = screen
        self._collections = collections
        self._engine = engine
        self._liquidity_target = liquidity_target_per_day
        self._url_builder = url_builder

    async def run(self, collection_address: str, *, limit: int = 100) -> PipelineReport:
        polled = await self._poller.run(collection_address, limit=limit)
        if not polled.discovered:
            return PipelineReport(0, 0, 0, 0, 0, 0)

        scored = 0
        risk_flagged = 0
        matched = 0
        delivered = 0
        dropped = 0

        for listing in polled.discovered:
            collection_id = listing.item.collection_id

            snapshot = await self._features.load(collection_id)
            if snapshot is None:
                snapshot = (await self._rebuild.run(collection_id)).features

            estimate = await self._scorer.run(listing)
            collection = await self._collections.get_collection(collection_id)
            collection = (
                collection if collection is not None else _fallback_collection(collection_id)
            )

            risk = await self._screen.run(listing, collection=collection)
            risk_flags = tuple(flag.code for flag in risk.flags)
            if risk_flags:
                risk_flagged += 1

            score = ListingScore(
                listing=listing,
                fair_price=estimate.estimate.value,
                confidence=estimate.estimate.confidence,
                discount=estimate.discount,
                liquidity=normalize_liquidity(
                    snapshot.sales_per_day, target_per_day=self._liquidity_target
                ),
                sales_per_day=snapshot.sales_per_day,
                risk_value=risk.value,
                floor_p5=snapshot.floor_p5,
                median_7d=snapshot.median_7d,
                sales_7d=snapshot.sales_7d,
                floor_24h_change=snapshot.floor_24h_change,
                risk_flags=risk_flags,
                collection_name=collection.name,
                getgems_url=self._url_builder(listing.item.id),
            )
            scored += 1

            report = await self._engine.deliver(score)
            matched += report.matched
            delivered += report.sent
            dropped += (
                report.deduped
                + report.rate_limited
                + report.quiet
                + report.paused
                + report.rejected
            )

        return PipelineReport(
            discovered=polled.discovered_count,
            scored=scored,
            risk_flagged=risk_flagged,
            matched=matched,
            delivered=delivered,
            dropped=dropped,
            listings=polled.discovered,
        )
