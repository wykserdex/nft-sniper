"""Репозитории контекста sources (протоколы; реализации —, Postgres)."""

from collections.abc import Sequence
from datetime import datetime
from typing import Protocol

from nftsniper.contexts.sources.domain.collection import Collection
from nftsniper.contexts.sources.domain.listing import Listing
from nftsniper.contexts.sources.domain.sale import SaleEvent


class ListingRepository(Protocol):
    async def save(self, listing: Listing) -> None:
        """Upsert по (marketplace, external_id) — идемпотентность (ТЗ §5)."""
        ...

    async def get(self, listing_id: str) -> Listing | None: ...

    async def get_by_dedup_key(self, dedup_key: str) -> Listing | None: ...

    async def list_active(
        self, collection_id: str | None = None, limit: int = 200
    ) -> Sequence[Listing]: ...


class SaleRepository(Protocol):
    async def get(self, sale_id: str) -> SaleEvent | None: ...

    async def add(self, sale: SaleEvent) -> None: ...

    async def list_by_item(self, item_id: str, since: datetime) -> Sequence[SaleEvent]: ...

    async def list_by_collection(
        self, collection_id: str, since: datetime, limit: int = 1000
    ) -> Sequence[SaleEvent]: ...


class CollectionRepository(Protocol):
    async def get(self, address: str) -> Collection | None: ...

    async def save(self, collection: Collection) -> None: ...
