"""Гейт изменения модели: сравнительный бэктест baseline vs candidate.

Критерий ТЗ §7: «любое изменение valuation прогоняется через бэктест и даёт
сравнимый отчёт». Кандидат деплоится, только если сам проходит порог ошибки
и не регрессирует относительно baseline больше, чем на tolerance.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from nftsniper.contexts.sources.domain.item import Item
from nftsniper.contexts.sources.domain.listing import Listing
from nftsniper.contexts.sources.domain.marketplace import Marketplace
from nftsniper.contexts.sources.domain.sale import SaleEvent
from nftsniper.contexts.valuation.adapters.ensemble import EnsemblePriceModel
from nftsniper.contexts.valuation.application.backtest import BacktestReport
from nftsniper.contexts.valuation.application.model_gate import (
    ModelComparisonReport,
    compare_models,
)
from nftsniper.contexts.valuation.domain.fair_price import (
    CollectionFeatures,
    EstimationMethod,
    FairPriceEstimate,
)
from nftsniper.shared.money import TONAmount
from nftsniper.shared.ton_address import TonAddress

D = Decimal
NOW = datetime(2026, 8, 31, 12, 0, 0, tzinfo=UTC)
COLL = "EQChoaGhoaGhoaGhoaGhoaGhoaGhoaGhoaGhoaGhoaGhodWi"
SELLER = TonAddress(workchain=0, raw_bytes=bytes([0xD1]) * 32)
BUYER = TonAddress(workchain=0, raw_bytes=bytes([0xE1]) * 32)

ITEM_COUNT = 24
BASE_PRICE = 88


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
        sales.append(
            SaleEvent(
                id=f"tx-{i}",
                item_id=item_id,
                collection_id=COLL,
                price=price,
                buyer=BUYER,
                seller=SELLER,
                tx_hash=f"tx-{i}",
                sold_at=start + timedelta(hours=6 * i),
                marketplace=Marketplace.GETGEMS,
            )
        )
    return sales, listings, items


class ConstantPriceModel:
    """Заведомо плохая модель: всегда 1 TON → медианная ошибка ~0.99."""

    model_version = "test.constant"

    async def estimate(self, listing: Listing, features: CollectionFeatures) -> FairPriceEstimate:
        value = TONAmount.from_ton(D("1"))
        return FairPriceEstimate(
            value=value,
            confidence=D("0.5"),
            method=EstimationMethod.FLOOR_BASED,
            lower_bound=value,
            upper_bound=value,
            sample_size=1,
            explanation=("constant model",),
            model_version=self.model_version,
        )


def _report(median: str, *, threshold: str = "0.40") -> BacktestReport:
    error = D(median)
    return BacktestReport(
        checked=10,
        median_error=error,
        mean_error=error,
        errors=(error,),
        all_explainable=True,
        threshold=D(threshold),
    )


async def test_compare_models_rejects_worse_candidate() -> None:
    sales, listings, items = _scenario()
    report = await compare_models(
        baseline=EnsemblePriceModel(),
        candidate=ConstantPriceModel(),
        sales=sales,
        active_listings=listings,
        item_by_id=items,
    )
    assert report.baseline.passed is True
    assert report.candidate.passed is False
    assert report.delta > D("0")
    assert report.promote is False
    assert "REJECT" in report.summary


async def test_compare_models_equal_models_promote() -> None:
    sales, listings, items = _scenario()
    report = await compare_models(
        baseline=EnsemblePriceModel(),
        candidate=EnsemblePriceModel(),
        sales=sales,
        active_listings=listings,
        item_by_id=items,
    )
    assert report.delta == D("0")
    assert report.baseline.passed is True
    assert report.candidate.passed is True
    assert report.promote is True
    assert "PROMOTE" in report.summary


def test_comparison_report_gate_logic() -> None:
    # Регрессия в пределах tolerance → promote.
    ok = ModelComparisonReport(
        baseline=_report("0.30"),
        candidate=_report("0.33"),
        tolerance=D("0.05"),
    )
    assert ok.delta == D("0.03")
    assert ok.promote is True

    # Регрессия больше tolerance → reject.
    bad = ModelComparisonReport(
        baseline=_report("0.30"),
        candidate=_report("0.33"),
        tolerance=D("0.01"),
    )
    assert bad.promote is False

    # Кандидат сам не прошёл порог → reject даже при нулевой дельте.
    failing = ModelComparisonReport(
        baseline=_report("0.30"),
        candidate=_report("0.45"),
        tolerance=D("0.50"),
    )
    assert failing.candidate.passed is False
    assert failing.promote is False


async def test_compare_models_empty_data() -> None:
    report = await compare_models(
        baseline=EnsemblePriceModel(),
        candidate=EnsemblePriceModel(),
        sales=[],
        active_listings=[],
        item_by_id={},
    )
    assert report.baseline.checked == 0
    assert report.candidate.checked == 0
    assert report.promote is False
