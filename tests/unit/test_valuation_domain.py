"""Домен valuation: Discount, FairPriceEstimate, CollectionFeatures, LiquidityScore."""

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from nftsniper.contexts.valuation.domain import (
    CollectionFeatures,
    Discount,
    DiscountError,
    EstimationMethod,
    FairPriceEstimate,
    LiquidityScore,
)
from nftsniper.shared.money import TONAmount

D = Decimal
T0 = datetime(2026, 8, 31, 12, 0, 0, tzinfo=UTC)


def test_discount_matches_tz_example() -> None:
    # Пример из ТЗ §1: fair 207, цена 120 → -42%
    discount = Discount.calculate(TONAmount.from_ton(D("207")), TONAmount.from_ton(D("120")))
    assert discount.pct == "-42%"
    assert discount.value == D("87") / D("207")
    assert discount.meets_min(D("0.25"))
    assert not discount.meets_min(D("0.50"))


def test_discount_zero_and_positive_case() -> None:
    equal = Discount.calculate(TONAmount.from_ton(D("100")), TONAmount.from_ton(D("100")))
    assert equal.pct == "0%"
    over = Discount.calculate(TONAmount.from_ton(D("100")), TONAmount.from_ton(D("112")))
    assert over.pct == "+12%"
    assert not over.meets_min(D("0"))


def test_discount_rounding_half_up() -> None:
    # 42.6% → "+43%" / "-43%" (округление, не усечение)
    fair = TONAmount.from_ton(D("1000"))
    price = TONAmount.from_ton(D("574"))
    assert Discount.calculate(fair, price).pct == "-43%"
    price_hi = TONAmount.from_ton(D("426"))
    assert Discount.calculate(TONAmount.from_ton(D("750")), price_hi).pct == "-43%"


def test_discount_invalid_inputs() -> None:
    with pytest.raises(DiscountError, match="положительным"):
        Discount.calculate(TONAmount.zero(), TONAmount.from_ton(1))
    with pytest.raises(DiscountError, match="отрицательной"):
        Discount.calculate(TONAmount.from_ton(10), TONAmount.from_ton(D("-1")))


def test_fair_price_estimate_valid() -> None:
    est = FairPriceEstimate(
        value=TONAmount.from_ton(D("207")),
        confidence=D("0.78"),
        method=EstimationMethod.ENSEMBLE,
        lower_bound=TONAmount.from_ton(D("195")),
        upper_bound=TONAmount.from_ton(D("214")),
        sample_size=18,
        explanation=("Floor P5: 195 TON", "Медиана 18 продаж: 214 TON"),
    )
    assert est.interval() == (
        TONAmount.from_ton(D("195")),
        TONAmount.from_ton(D("214")),
    )


def test_fair_price_confidence_bounds() -> None:
    def make(confidence: Decimal) -> FairPriceEstimate:
        return FairPriceEstimate(
            value=TONAmount.from_ton(100),
            confidence=confidence,
            method=EstimationMethod.FLOOR_BASED,
            lower_bound=TONAmount.from_ton(90),
            upper_bound=TONAmount.from_ton(110),
            sample_size=5,
            explanation=("x",),
        )

    make(D("1"))
    make(D("0"))
    with pytest.raises(ValueError, match="confidence"):
        make(D("1.2"))
    with pytest.raises(ValueError, match="confidence"):
        make(D("-0.1"))


def test_fair_price_interval_consistency() -> None:
    with pytest.raises(ValueError, match="интервале"):
        FairPriceEstimate(
            value=TONAmount.from_ton(100),
            confidence=D("0.5"),
            method=EstimationMethod.FLOOR_BASED,
            lower_bound=TONAmount.from_ton(105),
            upper_bound=TONAmount.from_ton(110),
            sample_size=5,
            explanation=("x",),
        )
    with pytest.raises(ValueError, match="sample_size"):
        FairPriceEstimate(
            value=TONAmount.from_ton(100),
            confidence=D("0.5"),
            method=EstimationMethod.FLOOR_BASED,
            lower_bound=TONAmount.from_ton(90),
            upper_bound=TONAmount.from_ton(110),
            sample_size=-1,
            explanation=("x",),
        )


def test_liquidity_score() -> None:
    good = LiquidityScore(value=D("0.8"), sales_per_day=D("2.4"), basis="7d окно")
    assert good.meets_min(D("0.5"))
    assert not good.meets_min(D("0.9"))
    with pytest.raises(ValueError, match="liquidity"):
        LiquidityScore(value=D("1.5"), sales_per_day=D("1"), basis="")


def test_collection_features_stored() -> None:
    features = CollectionFeatures(
        collection_id="EQAnon",
        floor_p5=TONAmount.from_ton(195),
        median_7d=TONAmount.from_ton(214),
        volume_24h=TONAmount.from_ton(410),
        sales_per_day=D("2.4"),
        listings_count=140,
        floor_24h_change=D("-0.03"),
        floor_7d_change=D("-0.08"),
        as_of=T0,
        floor_history=(D("228"), D("224"), D("219")),
    )
    assert features.floor_p5.formatted == "195"
    assert features.floor_history[-1] == D("219")
