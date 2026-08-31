"""PollFragment: загрузка лотов Fragment в ListingRepository.

Падение Fragment не ломает остальные источники (критерий готовности):
use case ловит ``FragmentError`` и возвращает пустой результат с флагом
``source_unavailable`` — конвейер продолжает работать по другим источникам.
Лоты с неизвестной ценой или продавцом пропускаются (деградация).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from nftsniper.contexts.sources.application.clock import utcnow
from nftsniper.contexts.sources.domain.events import ListingDiscovered
from nftsniper.contexts.sources.domain.fragment import FragmentAuction, FragmentStatus
from nftsniper.contexts.sources.domain.item import Item
from nftsniper.contexts.sources.domain.listing import Listing, ListingStatus
from nftsniper.contexts.sources.domain.marketplace import Marketplace
from nftsniper.contexts.sources.ports.fragment import FragmentError, FragmentPort
from nftsniper.contexts.sources.ports.repositories import ListingRepository
from nftsniper.infrastructure.http.circuit_breaker import CircuitBreakerOpenError
from nftsniper.infrastructure.http.client import HttpError


def auction_to_listing(auction: FragmentAuction) -> Listing | None:
    """``FragmentAuction`` → ``Listing`` (Marketplace.FRAGMENT).

    None, если нет цены или продавца — такой лот нельзя положить в конвейер
    оценки (деградация, а не падение).
    """
    if auction.price is None or auction.asset.owner is None:
        return None
    item = Item(
        id=auction.asset.address or auction.external_id,
        collection_id=auction.asset.collection_id,
        index=0,
        name=auction.asset.name,
    )
    external_id = auction.external_id or auction.asset.address
    status = ListingStatus.SOLD if auction.status is FragmentStatus.SOLD else ListingStatus.ACTIVE
    return Listing(
        id=f"fragment:{external_id}",
        external_id=external_id,
        marketplace=Marketplace.FRAGMENT,
        item=item,
        price=auction.price,
        seller=auction.asset.owner,
        listed_at=None,
        status=status,
    )


@dataclass(frozen=True, slots=True)
class PollFragmentResult:
    """Итог опроса: новые листинги, события и флаг недоступности источника."""

    discovered: tuple[Listing, ...]
    events: tuple[ListingDiscovered, ...]
    source_unavailable: bool = False

    @property
    def discovered_count(self) -> int:
        return len(self.discovered)


class PollFragment:
    """Опрашивает FragmentPort, дедуплицирует по ``dedup_key`` и сохраняет."""

    def __init__(
        self,
        fragment: FragmentPort,
        listings: ListingRepository,
        *,
        clock: Callable[[], datetime] = utcnow,
    ) -> None:
        self._fragment = fragment
        self._listings = listings
        self._clock = clock

    async def run(
        self,
        collection_address: str,
        *,
        limit: int = 100,
    ) -> PollFragmentResult:
        try:
            auctions = await self._fragment.list_auctions(collection_address, limit=limit)
        except (FragmentError, HttpError, CircuitBreakerOpenError):
            # источник изолирован: падение Fragment не ломает остальные (ТЗ §7)
            return PollFragmentResult(discovered=(), events=(), source_unavailable=True)

        discovered: list[Listing] = []
        events: list[ListingDiscovered] = []
        for auction in auctions:
            listing = auction_to_listing(auction)
            if listing is None:
                continue
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
        return PollFragmentResult(
            discovered=tuple(discovered),
            events=tuple(events),
        )
