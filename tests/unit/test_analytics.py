"""Аналитика алертов: качество, контрфактуал, рекомендация порога."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from nftsniper.contexts.alerts.application.analytics import (
    AlertAnalytics,
    compute_counterfactual,
    compute_quality,
    recommend_threshold,
)
from nftsniper.contexts.alerts.domain.alert import Alert, Decision
from nftsniper.contexts.alerts.domain.outcome import Outcome
from nftsniper.shared.money import TONAmount
from tests.fakes import (
    InMemoryAlertRepository,
    InMemoryDecisionRepository,
    InMemoryOutcomeRepository,
)

D = Decimal
NOW = datetime(2026, 8, 31, 12, 0, 0, tzinfo=UTC)


def _alert(index: int, user: str = "u1") -> Alert:
    return Alert(
        id=f"al-{index}",
        user_id=user,
        listing_id=f"lg-{index}",
        valuation_id="v-1",
        dedup_key=f"getgems:lg-{index}",
        sent_at=NOW,
    )


def _decision(alert_id: str, action: str = "taken", user: str = "u1") -> Decision:
    return Decision(
        id=f"d-{alert_id}",
        alert_id=alert_id,
        user_id=user,
        action=action,
        latency_ms=500,
        created_at=NOW,
    )


def _outcome(
    alert_id: str,
    *,
    discount: str,
    price_24h: str | None = None,
    sold: str | None = None,
    user: str = "u1",
    alert_price: str = "120",
) -> Outcome:
    return Outcome(
        id=f"o-{alert_id}",
        alert_id=alert_id,
        user_id=user,
        listing_id=alert_id.replace("al-", "lg-"),
        alert_price=TONAmount.from_ton(D(alert_price)),
        fair_price=TONAmount.from_ton(D("200")),
        discount=D(discount),
        price_after_24h=TONAmount.from_ton(D(price_24h)) if price_24h else None,
        sold_price=TONAmount.from_ton(D(sold)) if sold else None,
        computed_at=NOW,
    )


def test_compute_quality_metrics() -> None:
    alerts = [_alert(i) for i in range(1, 5)]
    outcomes = [
        _outcome("al-1", discount="0.40", price_24h="220"),  # подтверждён, выигрыш
        _outcome("al-2", discount="0.35", price_24h="150"),  # не подтверждён, выигрыш
        _outcome("al-3", discount="0.30", price_24h="100"),  # не подтверждён, убыток
        _outcome("al-4", discount="0.50", price_24h="250"),  # подтверждён, выигрыш
    ]
    decisions = [_decision("al-1"), _decision("al-4")]

    report = compute_quality(alerts, outcomes, decisions)

    assert report.alerts_sent == 4
    assert report.with_data == 4
    assert report.confirmed == 2
    assert report.precision == D("0.5")
    assert report.take_rate == D("0.5")
    assert report.hit_rate == D("0.75")
    assert report.avg_discount == D("0.3875")


def test_compute_quality_empty() -> None:
    report = compute_quality([], [], [])
    assert report.precision is None
    assert report.take_rate is None
    assert report.hit_rate is None
    assert report.avg_discount is None


def test_compute_counterfactual() -> None:
    alerts = [_alert(i) for i in range(1, 5)]
    outcomes = [
        _outcome("al-1", discount="0.40", price_24h="220"),  # взяли, +100
        _outcome("al-2", discount="0.35", price_24h="150"),  # взяли, +30
        _outcome("al-3", discount="0.30", price_24h="100"),  # не взяли, -20
        _outcome("al-4", discount="0.50", price_24h="250"),  # не взяли, +130
    ]
    decisions = [_decision("al-1"), _decision("al-2")]

    report = compute_counterfactual(alerts, outcomes, decisions)

    assert report.tracked == 4
    assert report.taken == 2
    assert report.not_taken == 2
    assert report.spent_if_all == TONAmount.from_ton(D("480"))
    assert report.value_if_all == TONAmount.from_ton(D("720"))
    assert report.pnl_if_all == TONAmount.from_ton(D("240"))
    assert report.missed_pnl == TONAmount.from_ton(D("110"))  # -20 + 130


def test_recommend_threshold_not_enough_data() -> None:
    outcomes = [
        _outcome("al-1", discount="0.40", price_24h="220"),
        _outcome("al-2", discount="0.35", price_24h="150"),
    ]
    recommendation = recommend_threshold(outcomes, current=D("0.25"))
    assert recommendation.recommended == D("0.25")  # нет изменений
    assert recommendation.sample_size == 2
    assert "мало данных" in recommendation.reasons[0]


def test_recommend_threshold_meets_target() -> None:
    good = "220"  # >= fair 200 → подтверждён
    bad = "150"  # < fair 200 → нет
    outcomes = [
        _outcome("al-1", discount="0.50", price_24h=good),
        _outcome("al-2", discount="0.45", price_24h=good),
        _outcome("al-3", discount="0.40", price_24h=good),
        _outcome("al-4", discount="0.35", price_24h=bad),
        _outcome("al-5", discount="0.30", price_24h=good),
        _outcome("al-6", discount="0.25", price_24h=bad),
    ]
    recommendation = recommend_threshold(
        outcomes, current=D("0.25"), target_precision=D("0.8"), min_samples=3
    )
    assert recommendation.recommended == D("0.30")  # наименьший, где precision ≥ 0.8
    assert recommendation.sample_size == 5
    assert recommendation.precision == D("0.8")


def test_recommend_threshold_fallback_best_precision() -> None:
    good = "220"
    bad = "150"
    outcomes = [
        _outcome("al-1", discount="0.50", price_24h=good),
        _outcome("al-2", discount="0.45", price_24h=bad),
        _outcome("al-3", discount="0.40", price_24h=good),
        _outcome("al-4", discount="0.35", price_24h=good),
        _outcome("al-5", discount="0.30", price_24h=good),
        _outcome("al-6", discount="0.25", price_24h=bad),
    ]
    recommendation = recommend_threshold(
        outcomes, current=D("0.25"), target_precision=D("0.9"), min_samples=3
    )
    assert recommendation.recommended == D("0.30")  # лучшая precision 0.8 на 5 алертах
    assert recommendation.precision == D("0.8")
    assert recommendation.sample_size == 5
    assert "недостижима" in recommendation.reasons[0]


async def test_analytics_use_case_filters_by_user() -> None:
    alerts = InMemoryAlertRepository()
    outcomes = InMemoryOutcomeRepository()
    decisions = InMemoryDecisionRepository()

    for index in range(1, 5):
        await alerts.save(_alert(index))
        await outcomes.save(_outcome(f"al-{index}", discount="0.40", price_24h="220"))
    await decisions.save(_decision("al-1"))
    await decisions.save(_decision("al-2"))

    # Другой пользователь с плохим исходом — не должен влиять на u1.
    await alerts.save(_alert(9, user="u2"))
    await outcomes.save(_outcome("al-9", discount="0.10", price_24h="50", user="u2"))

    analytics = AlertAnalytics(alerts, outcomes, decisions)
    report = await analytics.quality("u1")
    assert report.alerts_sent == 4
    assert report.take_rate == D("0.5")
    assert report.precision == D("1.0")

    recommendation = await analytics.recommend("u1", current=D("0.25"))
    assert recommendation.recommended == D("0.40")
