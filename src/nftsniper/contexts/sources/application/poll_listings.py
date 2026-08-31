"""PollListings: опрос маркетплейса и публикация новых листингов.

Зависит только от портов (``MarketplacePort``, ``ListingRepository``), поэтому
адаптер GetGems заменяем на fake без изменений — критерий готовности.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from nftsniper.contexts.sources.application.clock import utcnow
from nftsniper.contexts.sources.domain.events import ListingDiscovered
from nftsniper.contexts.sources.domain.listing import Listing
from nftsniper.contexts.sources.ports import MarketplacePort
from nftsniper.contexts.sources.ports.repositories import ListingRepository


@dataclass(frozen=True, slots=True)
class PollListingsResult:
    """Итог опроса: новые листинги и доменные события для конвейера."""

    discovered: tuple[Listing, ...]
    events: tuple[ListingDiscovered, ...]

    @property
    def discovered_count(self) -> int:
        return len(self.discovered)


class PollListings:
    """Опрашивает MarketplacePort, дедуплицирует по ``dedup_key`` и сохраняет.

    Дедупликация по ``dedup_key`` (marketplace + внешний id листинга, ТЗ §5) —
    рестарт poller'а не плодит дубли. События ``ListingDiscovered`` идут дальше
    по конвейеру (valuator → notifier, ТЗ §6).
    """

    def __init__(
        self,
        marketplace: MarketplacePort,
        listings: ListingRepository,
        *,
        clock: Callable[[], datetime] = utcnow,
    ) -> None:
        self._marketplace = marketplace
        self._listings = listings
        self._clock = clock

    async def run(self, collection_address: str, *, limit: int = 100) -> PollListingsResult:
        discovered: list[Listing] = []
        events: list[ListingDiscovered] = []
        for listing in await self._marketplace.list_active_listings(
            collection_address, limit=limit
        ):
            existing = await self._listings.get_by_dedup_key(listing.dedup_key)
            if existing is not None:
                continue
            await self._listings.save(listing)
            discovered.append(listing)
            events.append(
                ListingDiscovered(
                    occurred_at=self._clock(),
                    listing_id=listing.id,
                    marketplace=listing.marketplace,
                    collection_id=listing.item.collection_id,
                    item_id=listing.item.id,
                    price=listing.price,
                )
            )
        return PollListingsResult(discovered=tuple(discovered), events=tuple(events))
