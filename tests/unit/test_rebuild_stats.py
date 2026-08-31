"""RebuildStats: пересчёт статистики из репозиториев в фич-стор."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from nftsniper.contexts.sources.domain.item import Item
from nftsniper.contexts.sources.domain.listing import Listing
from nftsniper.contexts.sources.domain.marketplace import Marketplace
from nftsniper.contexts.sources.domain.sale import SaleEvent
from nftsniper.contexts.valuation.application import RebuildStats
from nftsniper.shared.money import TONAmount
from nftsniper.shared.ton_address import TonAddress
from tests.fakes import InMemoryFeatureStore, InMemoryListingRepository, InMemorySaleRepository

COLL = "EQChoaGhoaGhoaGhoaGhoaGhoaGhoaGhoaGhoaGhoaGhodWi"
SELLER = TonAddress(workchain=0, raw_bytes=bytes([0xD1]) * 32)
BUYER = TonAddress(workchain=0, raw_bytes=bytes([0xE1]) * 32)
DAY0 = datetime(2026, 8, 31, 12, 0, 0, tzinfo=UTC)


def _listing(idx: int, price_nano: int) -> Listing:
    item = Item(id=f"EQItem{idx}", collection_id=COLL, index=idx, name=f"#{idx}")
    return Listing(
        id=f"getgems:lg-{idx}",
        external_id=f"lg-{idx}",
        marketplace=Marketplace.GETGEMS,
        item=item,
        price=TONAmount.from_nano(price_nano),
        seller=SELLER,
        listed_at=DAY0,
    )


def _sale(idx: int, price_nano: int, sold_at: datetime) -> SaleEvent:
    return SaleEvent(
        id=f"tx-{idx}",
        item_id=f"EQItem{idx}",
        collection_id=COLL,
        price=TONAmount.from_nano(price_nano),
        buyer=BUYER,
        seller=SELLER,
        tx_hash=f"tx-{idx}",
        sold_at=sold_at,
        marketplace=Marketplace.GETGEMS,
    )


async def test_rebuild_stats_first_run_not_incremental() -> None:
    listings = InMemoryListingRepository()
    await listings.save(_listing(1, 100_000_000_000))
    await listings.save(_listing(2, 200_000_000_000))
    sales = InMemorySaleRepository()
    for i in range(14):
        await sales.add(_sale(i, (100 + i) * 1_000_000_000, DAY0 - timedelta(hours=i * 12)))
    features = InMemoryFeatureStore()

    result = await RebuildStats(listings, sales, features, clock=lambda: DAY0).run(COLL)

    assert result.incremental is False
    assert result.features.floor_p5 == TONAmount.from_nano(100_000_000_000)
    assert result.features.sales_per_day == Decimal("2")  # 14 продаж / 7 дней
    assert result.liquidity.value == Decimal("0.4")  # 2 / 5
    stored = await features.load(COLL)
    assert stored is not None
    assert stored.floor_p5 == result.features.floor_p5


async def test_rebuild_stats_incremental_same_day() -> None:
    listings = InMemoryListingRepository()
    await listings.save(_listing(1, 100_000_000_000))
    sales = InMemorySaleRepository()
    features = InMemoryFeatureStore()

    rebuild = RebuildStats(listings, sales, features, clock=lambda: DAY0)
    first = await rebuild.run(COLL)
    assert first.incremental is False
    assert first.features.floor_history == (Decimal("100"),)

    second = await rebuild.run(COLL)
    assert second.incremental is True
    # снимок того же дня заменяется, история не растёт
    assert second.features.floor_history == (Decimal("100"),)


async def test_rebuild_stats_extends_history_next_day() -> None:
    listings = InMemoryListingRepository()
    await listings.save(_listing(1, 100_000_000_000))
    sales = InMemorySaleRepository()
    features = InMemoryFeatureStore()

    first_run = RebuildStats(listings, sales, features, clock=lambda: DAY0)
    await first_run.run(COLL)

    next_day = RebuildStats(listings, sales, features, clock=lambda: DAY0 + timedelta(days=1))
    result = await next_day.run(COLL)
    assert result.features.floor_history == (Decimal("100"), Decimal("100"))
