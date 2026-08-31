"""Аналитика алертов: качество, контрфактуал, калибровка порога.

Чистые функции считают метрики по спискам Alert/Outcome/Decision; use case
``AlertAnalytics`` читает репозитории по пользователю. Критерий готовности
ТЗ §7: «видно качество алертов в цифрах и рекомендация по порогу для
конкретного пользователя».
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal

from nftsniper.contexts.alerts.domain.alert import Alert, Decision, DecisionAction
from nftsniper.contexts.alerts.domain.outcome import Outcome
from nftsniper.contexts.alerts.ports import (
    AlertRepository,
    DecisionRepository,
    OutcomeRepository,
)
from nftsniper.shared.money import TONAmount

DEFAULT_TARGET_PRECISION = Decimal("0.8")
DEFAULT_MIN_SAMPLES = 3


@dataclass(frozen=True, slots=True)
class QualityReport:
    """Качество алертов в цифрах (ТЗ §10)."""

    alerts_sent: int
    outcomes: int
    with_data: int
    confirmed: int
    precision: Decimal | None  # доля алертов, где fair подтвердился (ТЗ §10)
    take_rate: Decimal | None  # доля алертов с «Взять» (ТЗ §10)
    hit_rate: Decimal | None  # доля алертов, где цена выросла
    avg_discount: Decimal | None


@dataclass(frozen=True, slots=True)
class CounterfactualReport:
    """«Что было бы, если бы вы взяли все алерты»."""

    alerts_total: int
    tracked: int
    taken: int
    not_taken: int
    spent_if_all: TONAmount  # сумма цен всех алертов
    value_if_all: TONAmount  # сумма финальных цен (продажа/24h/7d/1h)
    pnl_if_all: TONAmount  # value_if_all − spent_if_all
    missed_pnl: TONAmount  # недополученное по невзятым сделкам


@dataclass(frozen=True, slots=True)
class ThresholdRecommendation:
    """Рекомендация порога ``min_discount`` для пользователя."""

    current: Decimal
    recommended: Decimal
    target_precision: Decimal
    sample_size: int
    precision: Decimal | None
    reasons: tuple[str, ...]


def _ratio(numerator: int, denominator: int) -> Decimal | None:
    if denominator == 0:
        return None
    return Decimal(numerator) / Decimal(denominator)


def _pct(value: Decimal) -> str:
    return f"{int(value * 100)}%"


def compute_quality(
    alerts: Sequence[Alert],
    outcomes: Sequence[Outcome],
    decisions: Sequence[Decision],
    *,
    tolerance: Decimal = Decimal("0"),
) -> QualityReport:
    """Метрики качества по сырым спискам (чистая функция)."""
    scored = [outcome for outcome in outcomes if outcome.has_data]
    confirmed = sum(1 for outcome in scored if outcome.confirmed_24h(tolerance=tolerance) is True)
    winning = sum(1 for outcome in scored if outcome.is_winning() is True)
    taken = sum(1 for decision in decisions if decision.action == DecisionAction.TAKEN)
    discounts = [outcome.discount for outcome in outcomes]
    avg_discount = sum(discounts, Decimal(0)) / len(discounts) if discounts else None
    return QualityReport(
        alerts_sent=len(alerts),
        outcomes=len(outcomes),
        with_data=len(scored),
        confirmed=confirmed,
        precision=_ratio(confirmed, len(scored)),
        take_rate=_ratio(taken, len(alerts)),
        hit_rate=_ratio(winning, len(scored)),
        avg_discount=avg_discount,
    )


def compute_counterfactual(
    alerts: Sequence[Alert],
    outcomes: Sequence[Outcome],
    decisions: Sequence[Decision],
) -> CounterfactualReport:
    """«Если бы вы взяли все алерты»: суммарный PnL и упущенное."""
    by_alert = {outcome.alert_id: outcome for outcome in outcomes}
    taken_ids = {
        decision.alert_id for decision in decisions if decision.action == DecisionAction.TAKEN
    }
    tracked = 0
    taken_count = 0
    not_taken_count = 0
    spent = TONAmount.zero()
    value = TONAmount.zero()
    missed = TONAmount.zero()
    for alert in alerts:
        outcome = by_alert.get(alert.id)
        if outcome is None:
            continue
        tracked += 1
        final = outcome.final_price()
        spent = spent.add(outcome.alert_price)
        value = value.add(final)
        if alert.id in taken_ids:
            taken_count += 1
        else:
            not_taken_count += 1
            missed = missed.add(final.sub(outcome.alert_price))
    return CounterfactualReport(
        alerts_total=len(alerts),
        tracked=tracked,
        taken=taken_count,
        not_taken=not_taken_count,
        spent_if_all=spent,
        value_if_all=value,
        pnl_if_all=value.sub(spent),
        missed_pnl=missed,
    )


def recommend_threshold(
    outcomes: Sequence[Outcome],
    *,
    current: Decimal,
    target_precision: Decimal = DEFAULT_TARGET_PRECISION,
    min_samples: int = DEFAULT_MIN_SAMPLES,
) -> ThresholdRecommendation:
    """Рекомендация порога min_discount (чистая функция).

    Правило: среди наблюдаемых дискаунтов ищется наименьший порог, на котором
    precision алертов с дискаунтом ≥ порога достигает ``target_precision`` при
    выборке ≥ ``min_samples``. Нет такого — берётся порог с максимальной
    precision; нет данных — остаётся текущий.
    """
    scored = [outcome for outcome in outcomes if outcome.confirmed_24h() is not None]
    if len(scored) < min_samples:
        return ThresholdRecommendation(
            current=current,
            recommended=current,
            target_precision=target_precision,
            sample_size=len(scored),
            precision=None,
            reasons=(f"мало данных: {len(scored)} < {min_samples} исходов с 24h",),
        )

    candidates = sorted({outcome.discount for outcome in scored})
    best: tuple[Decimal, int, Decimal] | None = None  # (порог, выборка, precision)
    for threshold in candidates:
        eligible = [outcome for outcome in scored if outcome.discount >= threshold]
        count = len(eligible)
        if count < min_samples:
            continue
        good = sum(1 for outcome in eligible if outcome.confirmed_24h() is True)
        precision = _ratio(good, count)
        if precision is None:
            continue
        if precision >= target_precision:
            return ThresholdRecommendation(
                current=current,
                recommended=threshold,
                target_precision=target_precision,
                sample_size=count,
                precision=precision,
                reasons=(
                    f"порог {_pct(threshold)}: precision {_pct(precision)} "
                    f"≥ цель {_pct(target_precision)} на {count} алертах",
                ),
            )
        if best is None or precision > best[2]:
            best = (threshold, count, precision)

    if best is not None:
        threshold, count, precision = best
        return ThresholdRecommendation(
            current=current,
            recommended=threshold,
            target_precision=target_precision,
            sample_size=count,
            precision=precision,
            reasons=(
                f"цель {_pct(target_precision)} недостижима; лучший порог "
                f"{_pct(threshold)} (precision {_pct(precision)}, {count} алертов)",
            ),
        )
    return ThresholdRecommendation(
        current=current,
        recommended=current,
        target_precision=target_precision,
        sample_size=len(scored),
        precision=None,
        reasons=("нет порогов с достаточной выборкой",),
    )


class AlertAnalytics:
    """Качество алертов в цифрах + рекомендация порога (use case)."""

    def __init__(
        self,
        alerts: AlertRepository,
        outcomes: OutcomeRepository,
        decisions: DecisionRepository,
    ) -> None:
        self._alerts = alerts
        self._outcomes = outcomes
        self._decisions = decisions

    async def quality(self, user_id: str, *, tolerance: Decimal = Decimal("0")) -> QualityReport:
        return compute_quality(
            await self._alerts.list_by_user(user_id),
            await self._outcomes.list_by_user(user_id),
            await self._decisions.list_by_user(user_id),
            tolerance=tolerance,
        )

    async def counterfactual(self, user_id: str) -> CounterfactualReport:
        return compute_counterfactual(
            await self._alerts.list_by_user(user_id),
            await self._outcomes.list_by_user(user_id),
            await self._decisions.list_by_user(user_id),
        )

    async def recommend(
        self,
        user_id: str,
        *,
        current: Decimal,
        target_precision: Decimal = DEFAULT_TARGET_PRECISION,
        min_samples: int = DEFAULT_MIN_SAMPLES,
    ) -> ThresholdRecommendation:
        outcomes = await self._outcomes.list_by_user(user_id)
        return recommend_threshold(
            outcomes,
            current=current,
            target_precision=target_precision,
            min_samples=min_samples,
        )
