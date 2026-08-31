"""Use cases оценки: EstimateFairPrice и ScoreListing.

Оба зависят только от портов (``PriceModelPort``, ``FeatureStorePort``,
``ValuationRepository``) — модель-адаптер заменяема без изменений в use cases
(критерий гексагональной архитектуры).

``EstimateFairPrice`` — оценка + сохранение в valuations (аудит, ТЗ §5);
``ScoreListing`` — оценка + дискаунт + доменное событие ``ListingScored``
для конвейера (matcher → notifier, ТЗ §6).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from nftsniper.contexts.sources.application.clock import utcnow
from nftsniper.contexts.sources.domain.listing import Listing
from nftsniper.contexts.valuation.application.stats import InsufficientDataError
from nftsniper.contexts.valuation.domain.discount import Discount
from nftsniper.contexts.valuation.domain.events import ListingScored
from nftsniper.contexts.valuation.domain.fair_price import FairPriceEstimate
from nftsniper.contexts.valuation.ports import (
    FeatureStorePort,
    PriceModelPort,
    ValuationRepository,
)


class EstimateFairPrice:
    """Оценить листинг и сохранить результат для аудита (ТЗ §5)."""

    def __init__(
        self,
        model: PriceModelPort,
        features: FeatureStorePort,
        valuations: ValuationRepository,
    ) -> None:
        self._model = model
        self._features = features
        self._valuations = valuations

    async def run(self, listing: Listing) -> FairPriceEstimate:
        collection_id = listing.item.collection_id
        snapshot = await self._features.load(collection_id)
        if snapshot is None:
            msg = f"нет признаков для коллекции {collection_id} — сначала RebuildStats"
            raise InsufficientDataError(msg)
        estimate = await self._model.estimate(listing, snapshot)
        await self._valuations.save(listing.id, estimate)
        return estimate


@dataclass(frozen=True, slots=True)
class ScoredListing:
    """Итог скрининга: оценка, дискаунт и событие для конвейера."""

    estimate: FairPriceEstimate
    discount: Discount
    event: ListingScored


class ScoreListing:
    """Оценить листинг и посчитать дискаунт к цене листинга (ТЗ §4)."""

    def __init__(
        self,
        estimator: EstimateFairPrice,
        *,
        clock: Callable[[], datetime] = utcnow,
    ) -> None:
        self._estimator = estimator
        self._clock = clock

    async def run(self, listing: Listing) -> ScoredListing:
        estimate = await self._estimator.run(listing)
        discount = Discount.calculate(estimate.value, listing.price)
        event = ListingScored(
            occurred_at=self._clock(),
            listing_id=listing.id,
            fair_price=estimate.value,
            discount=discount.value,
            confidence=estimate.confidence,
            method=estimate.method.value,
            model_version=estimate.model_version,
        )
        return ScoredListing(estimate=estimate, discount=discount, event=event)
