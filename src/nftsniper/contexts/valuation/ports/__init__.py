"""Порты контекста valuation: PriceModelPort, FeatureStorePort, репозитории."""

from typing import Protocol

from nftsniper.contexts.sources.domain.listing import Listing
from nftsniper.contexts.valuation.domain.fair_price import (
    CollectionFeatures,
    FairPriceEstimate,
)


class PriceModelPort(Protocol):
    """Модель оценки (: ансамбль floor/comps/trait/momentum)."""

    @property
    def model_version(self) -> str:
        """Версия модели — сохраняется в valuations для аудита (ТЗ §5)."""
        ...

    async def estimate(
        self, listing: Listing, features: CollectionFeatures
    ) -> FairPriceEstimate: ...


class FeatureStorePort(Protocol):
    """Хранилище признаков коллекции (: price_stats)."""

    async def load(self, collection_id: str) -> CollectionFeatures | None: ...


class ValuationRepository(Protocol):
    async def save(self, listing_id: str, estimate: FairPriceEstimate) -> str:
        """Сохранить оценку, вернуть id записи valuations (ТЗ §5)."""
        ...

    async def get_by_listing(self, listing_id: str) -> FairPriceEstimate | None: ...
