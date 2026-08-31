"""Ансамбль оценки: floor/comps/trait/momentum, confidence, интервал."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from nftsniper.contexts.sources.domain.item import Item, Trait, TraitSet
from nftsniper.contexts.sources.domain.listing import Listing
from nftsniper.contexts.sources.domain.marketplace import Marketplace
from nftsniper.contexts.valuation.adapters.comparable_sales import sales_7d_count
from nftsniper.contexts.valuation.adapters.ensemble import EnsemblePriceModel
from nftsniper.contexts.valuation.adapters.trait_model import rarity_multiplier, rarity_signal
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


def _ton(value: str) -> TONAmount:
    return TONAmount.from_ton(D(value))


def _features(
    *,
    floor: str = "100",
    median: str = "100",
    sales_per_day: str = "0",
    listings: int = 20,
    change_7d: str = "0",
    history: tuple[Decimal, ...] = (),
) -> CollectionFeatures:
    return CollectionFeatures(
        collection_id=COLL,
        floor_p5=_ton(floor),
        median_7d=_ton(median),
        volume_24h=_ton("0"),
        sales_per_day=D(sales_per_day),
        listings_count=listings,
        floor_24h_change=D("0"),
        floor_7d_change=D(change_7d),
        as_of=NOW,
        floor_history=history,
    )


def _item(*, traits: tuple[Trait, ...] = (), rarity_rank: str | None = None) -> Item:
    return Item(
        id="EQItem1",
        collection_id=COLL,
        index=1,
        name="#1",
        traits=TraitSet(traits=traits),
        rarity_rank=D(rarity_rank) if rarity_rank is not None else None,
    )


def _listing(item: Item, price: str = "80") -> Listing:
    return Listing(
        id="getgems:lg-1",
        external_id="lg-1",
        marketplace=Marketplace.GETGEMS,
        item=item,
        price=_ton(price),
        seller=SELLER,
        listed_at=NOW,
    )


async def _estimate(features: CollectionFeatures, item: Item) -> FairPriceEstimate:
    model = EnsemblePriceModel()
    return await model.estimate(_listing(item), features)


# ── покрытие и поведение по данным ──────────────────────────────────────


async def test_floor_only_is_explainable_with_low_confidence() -> None:
    """Нет продаж и трейтов: оценка = floor, confidence < 0.5 (ТЗ §4)."""
    estimate = await _estimate(_features(), _item())
    assert estimate.value == _ton("100")
    assert estimate.confidence < D("0.5")
    assert estimate.method is EstimationMethod.ENSEMBLE
    assert estimate.explanation  # всегда объяснима
    assert estimate.lower_bound <= estimate.value <= estimate.upper_bound


async def test_full_data_high_confidence_and_explanation() -> None:
    features = _features(floor="100", median="100", sales_per_day="2")
    item = _item(traits=(Trait(name="background", value="gold", rarity=D("0.5")),))
    estimate = await _estimate(features, item)
    assert estimate.confidence >= D("0.5")
    joined = " ".join(estimate.explanation)
    assert "Comparable sales" in joined
    assert "Trait-модель" in joined
    assert "Ансамбль" in joined


async def test_momentum_lowers_value_on_falling_market() -> None:
    flat = await _estimate(_features(history=()), _item())
    falling_features = _features(
        change_7d="-0.2",
        history=tuple(D(str(n)) for n in (100, 100, 100, 100, 100, 100, 100, 100)),
    )
    falling = await _estimate(falling_features, _item())
    assert falling.value < flat.value
    joined = " ".join(falling.explanation)
    assert "Momentum" in joined
    assert "Momentum" not in " ".join(flat.explanation)


async def test_rarer_item_gets_higher_estimate() -> None:
    features = _features(median="110", sales_per_day="2")
    rare = await _estimate(features, _item(rarity_rank="0.05"))
    common = await _estimate(features, _item(rarity_rank="0.95"))
    assert rare.value > common.value


async def test_interval_is_p25_p75_of_components() -> None:
    features = _features(floor="100", median="130", sales_per_day="2")
    item = _item(traits=(Trait(name="bg", value="gold", rarity=D("0.5")),))
    estimate = await _estimate(features, item)
    # три компоненты: floor 100, comps 130, trait (130 × 1.0 = 130)
    assert estimate.lower_bound == _ton("100")
    assert estimate.upper_bound == _ton("130")
    assert estimate.lower_bound <= estimate.value <= estimate.upper_bound


async def test_model_version_is_reported() -> None:
    model = EnsemblePriceModel()
    assert model.model_version == "7.0.0"
    estimate = await model.estimate(_listing(_item()), _features())
    assert estimate.model_version == "7.0.0"


# ── вспомогательные функции ─────────────────────────────────────────────


def test_sales_7d_count_rounds_single_sale() -> None:
    features = _features(sales_per_day=str(D(1) / D(7)))
    assert sales_7d_count(features) == 1
    assert sales_7d_count(_features(sales_per_day="0")) == 0
    assert sales_7d_count(_features(sales_per_day="2")) == 14


def test_rarity_multiplier_bounds() -> None:
    assert rarity_multiplier(D("0.5")) == D("1")
    assert rarity_multiplier(D("1")) == D("1.5")
    assert rarity_multiplier(D("0")) == D("0.75")


def test_rarity_signal_none_without_data() -> None:
    assert rarity_signal(_item()) is None
    ranked = _item(rarity_rank="0.2")
    assert rarity_signal(ranked) == D("0.8")


async def test_invariants_hold_across_data_shapes() -> None:
    """На любом наборе данных оценка валидна: confidence 0..1, bounds ⊇ value."""
    cases = [
        (_features(), _item()),
        (_features(listings=3), _item()),
        (_features(sales_per_day="0.2"), _item()),
        (_features(sales_per_day="3"), _item(rarity_rank="0.01")),
        (_features(change_7d="-0.4", history=tuple(D(str(n)) for n in range(10))), _item()),
    ]
    for features, item in cases:
        estimate = await _estimate(features, item)
        assert D("0") <= estimate.confidence <= D("1")
        assert estimate.lower_bound <= estimate.value <= estimate.upper_bound
        assert estimate.explanation
