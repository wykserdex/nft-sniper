"""PollFragment: маппинг лотов, дедуп и изоляция источника."""

from __future__ import annotations

from decimal import Decimal

from nftsniper.contexts.sources.application import PollFragment
from nftsniper.contexts.sources.application.poll_fragment import auction_to_listing
from nftsniper.contexts.sources.domain.fragment import (
    FragmentAsset,
    FragmentAuction,
    FragmentKind,
    FragmentStatus,
)
from nftsniper.contexts.sources.domain.listing import ListingStatus
from nftsniper.contexts.sources.domain.marketplace import Marketplace
from nftsniper.shared.money import TONAmount
from nftsniper.shared.ton_address import parse_address
from tests.fakes import FakeFragmentPort, InMemoryListingRepository

COLLECTION = "0:4cac1688d0ed22d0a3db653285812b33d8c23fa9220c0dde5f7ab056b27e17cf"
SELLER = parse_address("0:0000000000000000000000000000000000000000000000000000000000000201")


def make_auction(
    name: str,
    *,
    address: str = "0:000000000000000000000000000000000000000000000000000000000000010a",
    price: str | None = "10",
    owner: bool = True,
    status: FragmentStatus = FragmentStatus.RESALE,
) -> FragmentAuction:
    asset = FragmentAsset(
        address=address,
        name=name,
        kind=FragmentKind.NUMBER,
        collection_id=COLLECTION,
        owner=SELLER if owner else None,
    )
    return FragmentAuction(
        asset=asset,
        price=TONAmount.from_ton(Decimal(price)) if price is not None else None,
        status=status,
        external_id=name.lstrip("@+").replace(" ", ""),
    )


def test_auction_to_listing_maps_fragment() -> None:
    listing = auction_to_listing(make_auction("+888 0000 1312", price="10"))
    assert listing is not None
    assert listing.marketplace is Marketplace.FRAGMENT
    assert listing.price == TONAmount.from_ton(10)
    assert listing.status is ListingStatus.ACTIVE
    assert listing.item.collection_id == COLLECTION
    assert listing.dedup_key == "fragment:88800001312"


def test_auction_to_listing_requires_price_and_owner() -> None:
    assert auction_to_listing(make_auction("x", price=None)) is None
    assert auction_to_listing(make_auction("x", owner=False)) is None


def test_auction_to_listing_sold_status() -> None:
    listing = auction_to_listing(make_auction("x", status=FragmentStatus.SOLD))
    assert listing is not None
    assert listing.status is ListingStatus.SOLD


async def test_poll_fragment_ingests_and_dedups() -> None:
    repository = InMemoryListingRepository()
    port = FakeFragmentPort(auctions=[make_auction("+888 0000 1312")])
    use_case = PollFragment(port, repository)

    first = await use_case.run(COLLECTION)
    assert first.discovered_count == 1
    assert first.source_unavailable is False
    assert len(first.events) == 1

    second = await use_case.run(COLLECTION)
    assert second.discovered_count == 0  # дедуп по dedup_key
    assert len(repository._data) == 1


async def test_poll_fragment_skips_unpriced() -> None:
    repository = InMemoryListingRepository()
    port = FakeFragmentPort(
        auctions=[make_auction("+888 0000 1312", price=None), make_auction("+888 0707 7007")]
    )
    result = await PollFragment(port, repository).run(COLLECTION)
    assert result.discovered_count == 1  # только лот с ценой и продавцом


async def test_source_failure_is_isolated() -> None:
    """ТЗ §7: «падение источника не ломает остальные» — пустой результат."""
    repository = InMemoryListingRepository()
    port = FakeFragmentPort(fail=True)
    result = await PollFragment(port, repository).run(COLLECTION)
    assert result.discovered_count == 0
    assert result.source_unavailable is True
