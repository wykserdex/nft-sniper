"""Домен alerts: AlertPolicy (условия ТЗ §4), Alert, Decision."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from nftsniper.contexts.alerts.domain import (
    Alert,
    AlertButton,
    AlertMessage,
    AlertPolicy,
    Decision,
    DecisionAction,
)
from nftsniper.contexts.valuation.domain import Discount
from nftsniper.shared.money import TONAmount

D = Decimal
T0 = datetime(2026, 8, 31, 12, 0, 0, tzinfo=UTC)


def default_policy() -> AlertPolicy:
    return AlertPolicy(
        min_discount=D("0.25"),
        min_confidence=D("0.50"),
        price_min=TONAmount.from_ton(10),
        price_max=TONAmount.from_ton(500),
        min_liquidity=D("0.2"),
        max_risk=D("0.5"),
        dedup_window=timedelta(hours=6),
    )


def good_args() -> dict[str, object]:
    return {
        "discount": Discount.calculate(TONAmount.from_ton(D("207")), TONAmount.from_ton(D("120"))),
        "confidence": D("0.78"),
        "price": TONAmount.from_ton(D("120")),
        "liquidity": D("0.6"),
        "risk": D("0.1"),
    }


def test_policy_allows_good_deal() -> None:
    allowed, reasons = default_policy().allows(**good_args())  # type: ignore[arg-type]
    assert allowed
    assert reasons == ()


def test_policy_rejects_weak_discount() -> None:
    args = good_args()
    args["discount"] = Discount.calculate(TONAmount.from_ton(D("100")), TONAmount.from_ton(D("95")))
    allowed, reasons = default_policy().allows(**args)  # type: ignore[arg-type]
    assert not allowed
    assert any("discount" in r for r in reasons)


def test_policy_rejects_low_confidence_and_price_out_of_range() -> None:
    args = good_args()
    args["confidence"] = D("0.3")
    args["price"] = TONAmount.from_ton(D("999"))
    allowed, reasons = default_policy().allows(**args)  # type: ignore[arg-type]
    assert not allowed
    assert len(reasons) == 2


def test_policy_rejects_high_risk_and_low_liquidity() -> None:
    args = good_args()
    args["risk"] = D("0.8")
    args["liquidity"] = D("0.05")
    allowed, reasons = default_policy().allows(**args)  # type: ignore[arg-type]
    assert not allowed
    assert len(reasons) == 2


def test_policy_validation() -> None:
    with pytest.raises(ValueError, match="price_min"):
        AlertPolicy(
            min_discount=D("0.1"),
            min_confidence=D("0.5"),
            price_min=TONAmount.from_ton(500),
            price_max=TONAmount.from_ton(10),
            min_liquidity=D("0.1"),
            max_risk=D("0.5"),
        )
    with pytest.raises(ValueError, match="min_discount"):
        AlertPolicy(
            min_discount=D("-0.1"),
            min_confidence=D("0.5"),
            price_min=TONAmount.from_ton(1),
            price_max=TONAmount.from_ton(10),
            min_liquidity=D("0.1"),
            max_risk=D("0.5"),
        )


def test_alert_message_id_set_once() -> None:
    alert = Alert(
        id="al-1",
        user_id="u-1",
        listing_id="lg-1",
        valuation_id="v-1",
        dedup_key="getgems:gg-9001",
        sent_at=T0,
    )
    delivered = alert.with_message_id("tg-msg-42")
    assert delivered.message_id == "tg-msg-42"
    with pytest.raises(ValueError, match="message_id"):
        delivered.with_message_id("other")
    assert alert.message_id is None


def test_decision_actions() -> None:
    for action in DecisionAction.ALL:
        decision = Decision(
            id="d-1",
            alert_id="al-1",
            user_id="u-1",
            action=action,
            latency_ms=850,
            created_at=T0,
        )
        assert decision.action == action
    with pytest.raises(ValueError, match="действие"):
        Decision(
            id="d-2",
            alert_id="al-1",
            user_id="u-1",
            action="yolo",
            latency_ms=1,
            created_at=T0,
        )
    with pytest.raises(ValueError, match="latency_ms"):
        Decision(
            id="d-3",
            alert_id="al-1",
            user_id="u-1",
            action="taken",
            latency_ms=-1,
            created_at=T0,
        )


def test_alert_message_with_buttons() -> None:
    message = AlertMessage(
        text="🔥 Deal 42%",
        buttons=(
            AlertButton(text="✅ Взять", callback_data="take:al-1"),
            AlertButton(text="❌ Скип", callback_data="skip:al-1"),
        ),
    )
    assert len(message.buttons) == 2
    assert message.buttons[0].callback_data == "take:al-1"
