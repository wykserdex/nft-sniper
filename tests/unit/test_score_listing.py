"""Use cases оценки: EstimateFairPrice + ScoreListing на fake-портах."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from nftsniper.contexts.sources.domain.item import Item
from nftsniper.contexts.sources.domain.listing import Listing
from nftsniper.contexts.sources.domain.marketplace import Marketplace
from nftsniper.contexts.valuation.adapters.ensemble import EnsemblePriceModel
from nftsniper.contexts.valuation.application.estimate_fair_price import (
    EstimateFairPrice,
    ScoreListing,
)
from nftsniper.contexts.valuation.application.stats import InsufficientDataError
from nftsniper.contexts.valuation.domain.discount import Discount
from nftsniper.contexts.valuation.domain.fair_price import CollectionFeatures
from nftsniper.shared.money import TONAmount
from nftsniper.shared.ton_address import TonAddress
from tests.fakes import InMemoryFeatureStore, InMemoryValuationRepository

D = Decimal
NOW = datetime(2026, 8, 31, 12, 0, 0, tzinfo=UTC)
COLL = "EQChoaGhoaGhoaGhoaGhoaGhoaGhoaGhoaGhoaGhoaGhodWi"
SELLER = TonAddress(workchain=0, raw_bytes=bytes([0xD1]) * 32)


def _features() -> CollectionFeatures:
    return CollectionFeatures(
        collection_id=COLL,
        floor_p5=TONAmount.from_ton(D("100")),
        median_7d=TONAmount.from_ton(D("120")),
        volume_24h=TONAmount.from_ton(D("0")),
        sales_per_day=D("2"),
        listings_count=20,
        floor_24h_change=D("0"),
        floor_7d_change=D("0"),
        as_of=NOW,
    )


def _listing(price: str = "80") -> Listing:
    item = Item(id="EQItem1", collection_id=COLL, index=1, name="#1")
    return Listing(
        id="getgems:lg-1",
        external_id="lg-1",
        marketplace=Marketplace.GETGEMS,
        item=item,
        price=TONAmount.from_ton(D(price)),
        seller=SELLER,
        listed_at=NOW,
    )


async def _build(
    with_features: bool = True,
) -> tuple[ScoreListing, InMemoryFeatureStore, InMemoryValuationRepository]:
    features = InMemoryFeatureStore()
    if with_features:
        await features.save(_features())
    valuations = InMemoryValuationRepository()
    estimator = EstimateFairPrice(EnsemblePriceModel(), features, valuations)
    return ScoreListing(estimator), features, valuations


async def test_score_listing_computes_discount_and_event() -> None:
    score, _, valuations = await _build()
    listing = _listing("80")
    result = await score.run(listing)

    # discount = (fair - price) / fair
    expected = Discount.calculate(result.estimate.value, listing.price)
    assert result.discount == expected
    assert result.discount.value > 0  # 80 дешевле fair

    event = result.event
    assert event.listing_id == listing.id
    assert event.fair_price == result.estimate.value
    assert event.confidence == result.estimate.confidence
    assert event.model_version == "7.0.0"
    assert event.method == "ensemble"

    # оценка сохранена для аудита (ТЗ §5)
    saved = await valuations.get_by_listing(listing.id)
    assert saved == result.estimate


async def test_estimate_fair_price_requires_features() -> None:
    features = InMemoryFeatureStore()  # пустой фич-стор
    valuations = InMemoryValuationRepository()
    estimator = EstimateFairPrice(EnsemblePriceModel(), features, valuations)
    with pytest.raises(InsufficientDataError):
        await estimator.run(_listing())


async def test_score_listing_requires_features() -> None:
    score, _, _ = await _build(with_features=False)
    with pytest.raises(InsufficientDataError):
        await score.run(_listing())


async def test_score_overpriced_listing_negative_discount() -> None:
    score, _, _ = await _build()
    result = await score.run(_listing("150"))  # дороже fair
    assert result.discount.value < 0
