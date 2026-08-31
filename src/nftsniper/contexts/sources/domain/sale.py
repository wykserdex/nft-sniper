"""Событие продажи предмета (факт из истории / on-chain)."""

from dataclasses import dataclass
from datetime import datetime

from nftsniper.contexts.sources.domain.marketplace import Marketplace
from nftsniper.shared.domain.base import Entity
from nftsniper.shared.money import TONAmount
from nftsniper.shared.ton_address import TonAddress


@dataclass(frozen=True, slots=True)
class SaleEvent(Entity):
    """Завершённая продажа. ``is_suspicious`` — отметка anti-scam:
    wash trading, fake-продажи и т.п. (ТЗ §4)."""

    id: str
    item_id: str
    collection_id: str
    price: TONAmount
    buyer: TonAddress
    seller: TonAddress
    tx_hash: str
    sold_at: datetime
    marketplace: Marketplace | None = None
    is_suspicious: bool = False
