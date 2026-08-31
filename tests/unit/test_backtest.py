"""Бэктест: медианная ошибка fair price против фактических продаж.

Критерий готовности ТЗ §7: «на историческом бэктесте медианная ошибка ниже
согласованного порога и оценка всегда объяснима». Сценарий синтетический,
детерминированный: 24 предмета по ценам 88–111 TON, продажи в течение 6 дней,
walk-forward без look-ahead.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from nftsniper.contexts.sources.domain.item import Item
from nftsniper.contexts.sources.domain.listing import Listing
from nftsniper.contexts.sources.domain.marketplace import Marketplace
from nftsniper.contexts.sources.domain.sale import SaleEvent
from nftsniper.contexts.valuation.adapters.ensemble import EnsemblePriceModel
from nftsniper.contexts.valuation.application.backtest import (
    DEFAULT_ERROR_THRESHOLD,
    run_backtest,
)
from nftsniper.shared.money import TONAmount
from nftsniper.shared.ton_address import TonAddress

D = Decimal
NOW = datetime(2026, 8, 31, 12, 0, 0, tzinfo=UTC)
COLL = "EQChoaGhoaGhoaGhoaGhoaGhoaGhoaGhoaGhoaGhoaGhodWi"
SELLER = TonAddress(workchain=0, raw_bytes=bytes([0xD1]) * 32)
BUYER = TonAddress(workchain=0, raw_bytes=bytes([0xE1]) * 32)

ITEM_COUNT = 24
BASE_PRICE = 88  # цены 88..111 TON


def _scenario() -> tuple[list[SaleEvent], list[Listing], dict[str, Item]]:
    sales: list[SaleEvent] = []
    listings: list[Listing] = []
    items: dict[str, Item] = {}
    start = NOW - timedelta(days=6)
    for i in range(ITEM_COUNT):
        item_id = f"EQItem{i:03d}"
        price = TONAmount.from_ton(D(str(BASE_PRICE + i)))
        items[item_id] = Item(id=item_id, collection_id=COLL, index=i, name=f"#{i}")
        listings.append(
            Listing(
                id=f"getgems:lg-{i}",
                external_id=f"lg-{i}",
                marketplace=Marketplace.GETGEMS,
                item=items[item_id],
                price=price,
                seller=SELLER,
                listed_at=start,
            )
        )
        sold_at = start + timedelta(hours=6 * i)
        sales.append(
            SaleEvent(
                id=f"tx-{i}",
                item_id=item_id,
                collection_id=COLL,
                price=price,
                buyer=BUYER,
                seller=SELLER,
                tx_hash=f"tx-{i}",
                sold_at=sold_at,
                marketplace=Marketplace.GETGEMS,
            )
        )
    return sales, listings, items


async def test_backtest_median_error_below_threshold() -> None:
    sales, listings, items = _scenario()
    report = await run_backtest(
        model=EnsemblePriceModel(),
        sales=sales,
        active_listings=listings,
        item_by_id=items,
    )
    # первая продажа пропускается (нет прошлого), остальные 23 сверены
    assert report.checked == ITEM_COUNT - 1
    assert report.all_explainable is True
    assert report.median_error < DEFAULT_ERROR_THRESHOLD
    assert report.median_error <= report.mean_error or report.median_error >= D("0")
    assert report.passed is True


async def test_backtest_is_strict_with_tight_threshold() -> None:
    sales, listings, items = _scenario()
    report = await run_backtest(
        model=EnsemblePriceModel(),
        sales=sales,
        active_listings=listings,
        item_by_id=items,
        threshold=D("0.02"),  # намеренно жёсткий порог
    )
    assert report.median_error > D("0.02")
    assert report.passed is False


async def test_backtest_empty_sales() -> None:
    report = await run_backtest(
        model=EnsemblePriceModel(),
        sales=[],
        active_listings=[],
        item_by_id={},
    )
    assert report.checked == 0
    assert report.passed is False
