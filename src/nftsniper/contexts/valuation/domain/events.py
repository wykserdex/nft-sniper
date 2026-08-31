"""Доменные события контекста valuation (конвейер, ТЗ §6)."""

from dataclasses import dataclass
from decimal import Decimal

from nftsniper.shared.domain.base import DomainEvent
from nftsniper.shared.money import TONAmount


@dataclass(frozen=True, slots=True)
class ListingScored(DomainEvent):
    """Valuator оценил листинг (ансамбль + risk screening пройдены)."""

    listing_id: str
    fair_price: TONAmount
    discount: Decimal
    confidence: Decimal
    method: str
    model_version: str
