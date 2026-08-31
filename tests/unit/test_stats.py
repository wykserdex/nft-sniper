"""Statistics Engine: эталонные значения на фикстурах + perf SLA."""

from __future__ import annotations

import time
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from nftsniper.contexts.sources.domain.item import Item
from nftsniper.contexts.sources.domain.listing import Listing
from nftsniper.contexts.sources.domain.marketplace import Marketplace
from nftsniper.contexts.sources.domain.sale import SaleEvent
from nftsniper.contexts.valuation.application.stats import (
    InsufficientDataError,
    WeightedPrice,
    append_floor_snapshot,
    compute_collection_stats,
    decay_weight,
    decayed_sales_median,
    floor_change,
    floor_p5,
    normalize_liquidity,
    percentile_nearest_rank,
    sales_in_window,
    sales_per_day,
    time_decayed_median,
    volume,
)
from nftsniper.contexts.valuation.domain.fair_price import CollectionFeatures
from nftsniper.shared.money import TONAmount
from nftsniper.shared.ton_address import TonAddress

D = Decimal
NOW = datetime(2026, 8, 31, 12, 0, 0, tzinfo=UTC)
COLL = "EQChoaGhoaGhoaGhoaGhoaGhoaGhoaGhoaGhoaGhoaGhodWi"
SELLER = TonAddress(workchain=0, raw_bytes=bytes([0xD1]) * 32)
BUYER = TonAddress(workchain=0, raw_bytes=bytes([0xE1]) * 32)


_ids = iter(range(1, 1_000_000))


def _listing(price_nano: int) -> Listing:
    index = next(_ids)
    item = Item(id=f"EQItem{index}", collection_id=COLL, index=index, name=f"#{index}")
    return Listing(
        id=f"getgems:lg-{price_nano}-{index}",
        external_id=f"lg-{price_nano}-{index}",
        marketplace=Marketplace.GETGEMS,
        item=item,
        price=TONAmount.from_nano(price_nano),
        seller=SELLER,
        listed_at=NOW,
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


def _ton(value: str) -> TONAmount:
    return TONAmount.from_ton(D(value))


# ── перцентили и floor ──────────────────────────────────────────────────


def test_percentile_nearest_rank() -> None:
    prices = [_ton(str(i)) for i in range(1, 11)]  # 1..10
    assert percentile_nearest_rank(prices, D("5")) == _ton("1")  # rank=1 → минимум
    assert percentile_nearest_rank(prices, D("50")) == _ton("5")
    assert percentile_nearest_rank(prices, D("95")) == _ton("10")


def test_percentile_empty_raises() -> None:
    with pytest.raises(InsufficientDataError):
        percentile_nearest_rank([], D("5"))


def test_floor_p5_ignores_single_junk_listing() -> None:
    # 99 листингов по 100 TON + один мусорный за 1 TON: P5 не должен упасть
    listings = [_listing(100_000_000_000) for _ in range(99)] + [_listing(1_000_000_000)]
    assert floor_p5(listings) == TONAmount.from_nano(100_000_000_000)


def test_floor_p5_empty_raises() -> None:
    with pytest.raises(InsufficientDataError):
        floor_p5([])


# ── затухание и медианы ─────────────────────────────────────────────────


def test_decay_weight_half_life() -> None:
    assert decay_weight(D("0")) == D("1")
    assert decay_weight(D("7")) == D("0.5")
    assert decay_weight(D("14")) == D("0.25")
    with pytest.raises(ValueError, match="полураспад"):
        decay_weight(D("1"), half_life_days=D("0"))


def test_time_decayed_median_plain() -> None:
    points = [
        WeightedPrice(price=_ton("100"), weight=D("1")),
        WeightedPrice(price=_ton("200"), weight=D("1")),
        WeightedPrice(price=_ton("300"), weight=D("1")),
    ]
    assert time_decayed_median(points) == _ton("200")


def test_time_decayed_median_weighted() -> None:
    points = [
        WeightedPrice(price=_ton("100"), weight=D("3")),
        WeightedPrice(price=_ton("200"), weight=D("1")),
    ]
    assert time_decayed_median(points) == _ton("100")  # свежие весят больше


def test_time_decayed_median_empty_raises() -> None:
    with pytest.raises(InsufficientDataError):
        time_decayed_median([])


def test_decayed_sales_median_fresh_dominates() -> None:
    sales = [
        _sale(1, 100_000_000_000, NOW),  # свежая, вес 1
        _sale(2, 200_000_000_000, NOW - timedelta(days=7)),  # вес 0.5
    ]
    median = decayed_sales_median(sales, now=NOW)
    assert median == TONAmount.from_nano(100_000_000_000)


def test_decayed_sales_median_excludes_outside_window() -> None:
    sales = [
        _sale(1, 100_000_000_000, NOW),
        _sale(2, 999_000_000_000, NOW - timedelta(days=8)),  # вне 7-дневного окна
    ]
    median = decayed_sales_median(sales, now=NOW)
    assert median == TONAmount.from_nano(100_000_000_000)


# ── окна, объёмы, темп ──────────────────────────────────────────────────


def test_sales_in_window_and_volume() -> None:
    sales = [
        _sale(1, 100, NOW),
        _sale(2, 200, NOW - timedelta(hours=25)),  # вне 24h
        _sale(3, 300, NOW - timedelta(days=6)),
        _sale(4, 400, NOW - timedelta(days=8)),  # вне 7d
    ]
    day = sales_in_window(sales, now=NOW, window=timedelta(days=1))
    assert [sale.id for sale in day] == ["tx-1"]
    assert volume(day) == TONAmount.from_nano(100)
    week = sales_in_window(sales, now=NOW, window=timedelta(days=7))
    assert [sale.id for sale in week] == ["tx-1", "tx-2", "tx-3"]


def test_sales_per_day() -> None:
    sales = [_sale(i, 100, NOW - timedelta(hours=i)) for i in range(14)]
    assert sales_per_day(sales, now=NOW) == D("2")  # 14 продаж / 7 дней


# ── momentum и история floor ────────────────────────────────────────────


def test_floor_change() -> None:
    history = (D("100"), D("90"), D("99"))
    assert floor_change(history, steps_back=1) == D("0.1")  # +10% за 24h
    assert floor_change(history, steps_back=2) == D("-0.01")
    assert floor_change(history, steps_back=7) is None  # истории не хватает


def test_floor_change_zero_base_is_none() -> None:
    assert floor_change((D("0"), D("100")), steps_back=1) is None


def test_append_floor_snapshot_same_day_replaces() -> None:
    history = (D("100"), D("110"))
    merged = append_floor_snapshot(history, D("105"), same_day_as_previous=True)
    assert merged == (D("100"), D("105"))


def test_append_floor_snapshot_new_day_appends_and_trims() -> None:
    history = tuple(D(str(i)) for i in range(1, 6))
    merged = append_floor_snapshot(history, D("6"), same_day_as_previous=False, max_len=5)
    assert merged == (D("2"), D("3"), D("4"), D("5"), D("6"))  # старейший вытеснен


# ── ликвидность ─────────────────────────────────────────────────────────


def test_normalize_liquidity() -> None:
    assert normalize_liquidity(D("2.5")) == D("0.5")
    assert normalize_liquidity(D("10")) == D("1")  # потолок
    assert normalize_liquidity(D("0")) == D("0")
    with pytest.raises(ValueError, match="target"):
        normalize_liquidity(D("1"), target_per_day=D("0"))


# ── итоговый пересчёт ───────────────────────────────────────────────────


def test_compute_collection_stats_end_to_end() -> None:
    listings = [_listing(100_000_000_000) for _ in range(20)]
    sales = [
        _sale(i, (100 + i) * 1_000_000_000, NOW - timedelta(hours=i * 6))
        for i in range(28)  # 28 продаж за 7 дней → sales_per_day = 4
    ]
    stats = compute_collection_stats(
        collection_id=COLL, active_listings=listings, sales=sales, now=NOW
    )
    features = stats.features
    assert features.floor_p5 == TONAmount.from_nano(100_000_000_000)
    assert features.listings_count == 20
    assert features.sales_per_day == D("4")
    # в 24h попадают продажи i=0..4 (каждые 6 часов): 100+101+102+103+104 = 510
    assert features.volume_24h == TONAmount.from_nano(510_000_000_000)
    assert features.floor_history == (D("100"),)
    assert features.floor_24h_change == D("0")  # истории не хватает
    assert features.floor_7d_change == D("0")
    assert stats.liquidity.value == D("0.8")  # 4 / 5
    assert stats.liquidity.meets_min(D("0.5"))


def test_compute_collection_stats_no_sales_falls_back_to_floor() -> None:
    listings = [_listing(120_000_000_000)]
    stats = compute_collection_stats(
        collection_id=COLL, active_listings=listings, sales=[], now=NOW
    )
    assert stats.features.median_7d == TONAmount.from_nano(120_000_000_000)
    assert stats.features.sales_per_day == D("0")
    assert stats.liquidity.value == D("0")


def test_compute_collection_stats_requires_listings() -> None:
    with pytest.raises(InsufficientDataError):
        compute_collection_stats(collection_id=COLL, active_listings=[], sales=[], now=NOW)


def test_compute_collection_stats_uses_previous_history() -> None:
    listings = [_listing(100_000_000_000)]
    previous = CollectionFeatures(
        collection_id=COLL,
        floor_p5=_ton("90"),
        median_7d=_ton("90"),
        volume_24h=_ton("0"),
        sales_per_day=D("0"),
        listings_count=1,
        floor_24h_change=D("0"),
        floor_7d_change=D("0"),
        as_of=datetime(2026, 8, 30, 12, 0, 0, tzinfo=UTC),
        floor_history=(D("90"),),
    )
    stats = compute_collection_stats(
        collection_id=COLL,
        active_listings=listings,
        sales=[],
        now=NOW,
        previous=previous,
    )
    # новый день → история продлилась; momentum 24h = (100-90)/90
    assert stats.features.floor_history == (D("90"), D("100"))
    assert stats.features.floor_24h_change == D("10") / D("90")


# ── SLA: 10k предметов ──────────────────────────────────────────────────


def test_recompute_10k_items_within_sla() -> None:
    listings = [_listing((100_000_000 + i) * 1_000_000) for i in range(10_000)]
    sales = [
        _sale(i, (50_000_000 + i) * 1_000_000, NOW - timedelta(minutes=i)) for i in range(10_000)
    ]
    started = time.monotonic()
    stats = compute_collection_stats(
        collection_id=COLL, active_listings=listings, sales=sales, now=NOW
    )
    elapsed = time.monotonic() - started
    assert stats.features.listings_count == 10_000
    # O(n log n) на 10k+10k — миллисекунды; щедрый порог против флаков CI
    assert elapsed < 2.0, f"пересчёт 10k предметов занял {elapsed:.2f} c"
