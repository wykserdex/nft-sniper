"""Порты контекста sources: MarketplacePort, ChainPort (ТЗ §7).

Адаптеры реализуют эти протоколы; use cases зависимы
только от протоколов — адаптеры заменяемы на fake в тестах.
"""

from collections.abc import Sequence
from datetime import datetime
from typing import Protocol

from nftsniper.contexts.sources.domain.chain import NftTransfer, WalletInfo
from nftsniper.contexts.sources.domain.collection import Collection
from nftsniper.contexts.sources.domain.item import Item
from nftsniper.contexts.sources.domain.listing import Listing
from nftsniper.contexts.sources.domain.sale import SaleEvent


class MarketplacePort(Protocol):
    """Маркетплейс (— GetGems): листинги, продажи, предметы, floor."""

    async def get_collection(self, address: str) -> Collection | None:
        """Коллекция по on-chain-адресу (None, если не найдена)."""
        ...

    async def get_item(self, address: str) -> Item | None:
        """Предмет по on-chain-адресу NFT."""
        ...

    async def list_active_listings(
        self,
        collection_address: str | None = None,
        limit: int = 100,
    ) -> Sequence[Listing]:
        """Активные листинги (все коллекции или одной)."""
        ...

    async def get_sales(
        self,
        collection_address: str,
        since: datetime,
        limit: int = 500,
    ) -> Sequence[SaleEvent]:
        """История продаж коллекции с даты ``since``."""
        ...


class ChainPort(Protocol):
    """On-chain (— TonAPI/TonCenter). Источник истины по ценам (ТЗ §3)."""

    async def get_nft_owner(self, address: str) -> str | None:
        """Владелец NFT (user-friendly адрес) или None, если NFT не существует."""
        ...

    async def get_nft_transfers(
        self,
        address: str,
        since: datetime | None = None,
        limit: int = 50,
    ) -> Sequence[NftTransfer]:
        """История трансферов NFT."""
        ...

    async def get_wallet(self, address: str) -> WalletInfo | None:
        """Метаданные кошелька (возраст, входящий объём) для risk-фильтров."""
        ...

    async def verify_sale(self, sale: SaleEvent) -> bool:
        """Сверка продажи с on-chain (расхождение >1% помечается флагом, ТЗ §3)."""
        ...
