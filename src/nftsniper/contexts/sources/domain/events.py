"""Доменные события контекста sources (конвейер, ТЗ §6)."""

from dataclasses import dataclass

from nftsniper.contexts.sources.domain.marketplace import Marketplace
from nftsniper.shared.domain.base import DomainEvent
from nftsniper.shared.money import TONAmount


@dataclass(frozen=True, slots=True)
class ListingDiscovered(DomainEvent):
    """Poller нашёл новый листинг (после нормализации и дедупликации)."""

    listing_id: str
    marketplace: Marketplace
    collection_id: str
    item_id: str
    price: TONAmount


@dataclass(frozen=True, slots=True)
class SaleIngested(DomainEvent):
    """Событие продажи загружено в историю."""

    sale_id: str
    collection_id: str
    item_id: str
    price: TONAmount
