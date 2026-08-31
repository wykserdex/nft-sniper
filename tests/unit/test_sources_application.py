"""Use cases sources: PollListings, IngestSale, BackfillHistory на fake'ах.

Доказывает критерий: use cases зависят только от портов — те же
тесты проходят и с GetGemsAdapter (см. tests/contract/), и с fake'ом.
"""

from datetime import UTC, datetime

from nftsniper.contexts.sources.application import (
    BackfillHistory,
    IngestSale,
    PollListings,
)
from nftsniper.contexts.sources.domain.item import Item, Trait, TraitSet
from nftsniper.contexts.sources.domain.listing import Listing, ListingStatus
from nftsniper.contexts.sources.domain.marketplace import Marketplace
from nftsniper.contexts.sources.domain.sale import SaleEvent
from nftsniper.shared.money import TONAmount
from nftsniper.shared.ton_address import TonAddress
from tests.fakes import FakeMarketplacePort, InMemoryListingRepository, InMemorySaleRepository

COLL = "EQChoaGhoaGhoaGhoaGhoaGhoaGhoaGhoaGhoaGhoaGhodWi"


def _addr(seed: int) -> TonAddress:
    return TonAddress(workchain=0, raw_bytes=bytes([seed]) * 32)


def _item(idx: int) -> Item:
    return Item(
        id=f"EQItem{idx:064x}"[:48],
        collection_id=COLL,
        index=idx,
        name=f"Number #{idx}",
        traits=TraitSet(traits=(Trait(name="Number", value=str(idx)),)),
    )


def _listing(idx: int, price_nano: int) -> Listing:
    return Listing(
        id=f"getgems:gg-{idx}",
        external_id=f"gg-{idx}",
        marketplace=Marketplace.GETGEMS,
        item=_item(idx),
        price=TONAmount.from_nano(price_nano),
        seller=_addr(0xD1),
        listed_at=datetime(2026, 8, 31, 12, 0, 0, tzinfo=UTC),
        status=ListingStatus.ACTIVE,
    )


def _sale(idx: int, price_nano: int, sold_at: datetime) -> SaleEvent:
    return SaleEvent(
        id=f"tx-{idx}",
        item_id=f"EQItem{idx:064x}"[:48],
        collection_id=COLL,
        price=TONAmount.from_nano(price_nano),
        buyer=_addr(0xE1),
        seller=_addr(0xD1),
        tx_hash=f"tx-{idx}",
        sold_at=sold_at,
        marketplace=Marketplace.GETGEMS,
    )


def _fixed_now() -> datetime:
    """Фиксированное «сейчас» для детерминированных окон бэкфилла."""
    return datetime(2026, 9, 1, tzinfo=UTC)


# ── PollListings ────────────────────────────────────────────────────────


async def test_poll_listings_discovers_new_and_skips_existing() -> None:
    marketplace = FakeMarketplacePort(listings=[_listing(1, 100), _listing(2, 200)])
    repository = InMemoryListingRepository()
    await repository.save(_listing(1, 100))  # уже известен → пропускается

    result = await PollListings(marketplace, repository).run(COLL)

    assert result.discovered_count == 1
    assert result.discovered[0].external_id == "gg-2"


async def test_poll_listings_emits_events() -> None:
    marketplace = FakeMarketplacePort(listings=[_listing(1, 100)])
    repository = InMemoryListingRepository()

    result = await PollListings(marketplace, repository).run(COLL)

    assert len(result.events) == 1
    event = result.events[0]
    assert event.listing_id == "getgems:gg-1"
    assert event.price.nano == 100


async def test_poll_listings_filters_by_collection() -> None:
    other = _listing(9, 100)
    other = Listing(
        id=other.id,
        external_id=other.external_id,
        marketplace=other.marketplace,
        item=Item(
            id=other.item.id,
            collection_id="EQOther",
            index=9,
            name="Other",
        ),
        price=other.price,
        seller=other.seller,
        listed_at=other.listed_at,
    )
    marketplace = FakeMarketplacePort(listings=[_listing(1, 100), other])
    repository = InMemoryListingRepository()

    result = await PollListings(marketplace, repository).run(COLL)

    assert result.discovered_count == 1
    assert result.discovered[0].external_id == "gg-1"


# ── IngestSale ──────────────────────────────────────────────────────────


async def test_ingest_sale_dedups_by_tx_hash() -> None:
    t1 = datetime(2026, 8, 30, 12, 0, 0, tzinfo=UTC)
    t2 = datetime(2026, 8, 31, 12, 0, 0, tzinfo=UTC)
    marketplace = FakeMarketplacePort(sales=[_sale(1, 100, t1), _sale(2, 200, t2)])
    repository = InMemorySaleRepository()
    await repository.add(_sale(1, 100, t1))

    result = await IngestSale(marketplace, repository).run(COLL, datetime(2026, 8, 1, tzinfo=UTC))

    assert result.ingested_count == 1
    assert result.ingested[0].id == "tx-2"
    assert len(result.events) == 1


async def test_ingest_sale_respects_since() -> None:
    t1 = datetime(2026, 7, 30, 12, 0, 0, tzinfo=UTC)  # раньше since
    t2 = datetime(2026, 8, 31, 12, 0, 0, tzinfo=UTC)
    marketplace = FakeMarketplacePort(sales=[_sale(1, 100, t1), _sale(2, 200, t2)])
    repository = InMemorySaleRepository()

    result = await IngestSale(marketplace, repository).run(COLL, datetime(2026, 8, 1, tzinfo=UTC))

    assert result.ingested_count == 1
    assert result.ingested[0].id == "tx-2"


# ── BackfillHistory ─────────────────────────────────────────────────────


async def test_backfill_ingests_all_and_is_idempotent() -> None:
    t1 = datetime(2026, 8, 30, 12, 0, 0, tzinfo=UTC)
    t2 = datetime(2026, 8, 31, 12, 0, 0, tzinfo=UTC)
    marketplace = FakeMarketplacePort(sales=[_sale(1, 100, t1), _sale(2, 200, t2)])
    repository = InMemorySaleRepository()
    backfill = BackfillHistory(IngestSale(marketplace, repository), clock=_fixed_now)

    result = await backfill.run(COLL, datetime(2026, 8, 1, tzinfo=UTC), limit=500)
    assert result.ingested == 2
    assert result.windows == 1  # окно неполное (2 < 500) → история исчерпана

    # повторный запуск идемпотентен
    again = await backfill.run(COLL, datetime(2026, 8, 1, tzinfo=UTC), limit=500)
    assert again.ingested == 0


async def test_backfill_windows_until_exhausted() -> None:
    """limit=1: каждое окно приносит 1 продажу → окон ровно столько, сколько продаж."""
    t1 = datetime(2026, 8, 30, 12, 0, 0, tzinfo=UTC)
    t2 = datetime(2026, 8, 31, 12, 0, 0, tzinfo=UTC)
    marketplace = FakeMarketplacePort(sales=[_sale(1, 100, t1), _sale(2, 200, t2)])
    repository = InMemorySaleRepository()
    backfill = BackfillHistory(IngestSale(marketplace, repository), clock=_fixed_now)

    result = await backfill.run(COLL, datetime(2026, 8, 1, tzinfo=UTC), limit=1)
    assert result.ingested == 2
    assert result.windows == 3  # 2 продажи + пустое окно-стоп
