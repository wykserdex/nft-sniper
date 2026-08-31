"""Ансамбль оценки (ТЗ §4).

Взвешенное среднее компонент: floor-based, comparable sales, trait-модель,
momentum. Веса зависят от размера выборки и свежести данных (уже
считает устойчивый floor и медиану с затуханием).

- **value** — взвешенное среднее точечных оценок компонент, затем поправка
  momentum (падающий рынок занижает fair price, ТЗ §4);
- **interval** — 25/75 перцентиль точечных оценок (ТЗ §4: «никогда одну
  цифру»); при одной компоненте расширяется ±10%;
- **confidence** — покрытие данных (доля номинальных весов) × согласие
  компонент (меньше разброс — выше уверенность), 0..1;
- **model_version** — версия модели, сохраняется в valuations для аудита;
- **explanation** — человекочитаемые причины по каждой компоненте.

Всё на Decimal (без float).
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from decimal import ROUND_HALF_UP, Decimal

from nftsniper.contexts.sources.domain.listing import Listing
from nftsniper.contexts.valuation.adapters.comparable_sales import estimate_comparable
from nftsniper.contexts.valuation.adapters.estimates import ModelEstimate, clamp, sample_quality
from nftsniper.contexts.valuation.adapters.floor_model import estimate_floor
from nftsniper.contexts.valuation.adapters.trait_model import estimate_traits
from nftsniper.contexts.valuation.domain.fair_price import (
    CollectionFeatures,
    EstimationMethod,
    FairPriceEstimate,
)
from nftsniper.shared.money import NANO_PER_TON, TONAmount

MODEL_VERSION = "7.0.0"

MOMENTUM_NOMINAL_WEIGHT = Decimal("0.10")
MOMENTUM_HISTORY_FOR_FULL = 7
MOMENTUM_MIN_MULTIPLIER = Decimal("0.50")
MOMENTUM_MAX_MULTIPLIER = Decimal("1.50")
MOMENTUM_EPSILON = Decimal("0.005")
_AGREEMENT_FLOOR = Decimal("0.4")
_TWO = Decimal(2)
_MIN_INTERVAL_POINTS = 2  # нужно ≥2 компоненты для P25/P75 интервала


def _ton(ton: Decimal) -> TONAmount:
    """Decimal TON → TONAmount с квантованием до nanoTON (без float)."""
    nano = int((ton * Decimal(NANO_PER_TON)).to_integral_value(rounding=ROUND_HALF_UP))
    return TONAmount.from_nano(max(0, nano))


def _nearest_rank(values: Sequence[TONAmount], p: Decimal) -> TONAmount:
    """Nearest-rank перцентиль по списку цен (p в [0, 100])."""
    ordered = sorted(values)
    rank = math.ceil(p * Decimal(len(ordered)) / Decimal(100))
    return ordered[max(0, rank - 1)]


def _signed_pct(change: Decimal) -> str:
    percent = (change * Decimal(100)).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    sign = "+" if percent > 0 else ""
    return f"{sign}{int(percent)}%"


def momentum_adjustment(features: CollectionFeatures) -> tuple[Decimal, Decimal, str | None]:
    """(множитель, вес, объяснение) по тренду floor за 7 дней.

    Множитель = ``clamp(1 + change * quality, 0.5, 1.5)``; при короткой
    истории или плоском тренде множитель = 1, объяснение — None.
    """
    history = features.floor_history
    if len(history) < _MIN_INTERVAL_POINTS:
        return Decimal(1), Decimal(0), None
    quality = sample_quality(len(history), MOMENTUM_HISTORY_FOR_FULL)
    change = features.floor_7d_change
    multiplier = clamp(
        Decimal(1) + change * quality, MOMENTUM_MIN_MULTIPLIER, MOMENTUM_MAX_MULTIPLIER
    )
    weight = MOMENTUM_NOMINAL_WEIGHT * quality
    if abs(change) <= MOMENTUM_EPSILON:
        return multiplier, weight, None
    explanation = (
        f"Momentum: floor 7д {_signed_pct(change)} → оценка ×{multiplier.quantize(Decimal('0.01'))}"
    )
    return multiplier, weight, explanation


class EnsemblePriceModel:
    """Адаптер ``PriceModelPort``: ансамбль floor/comps/trait/momentum."""

    @property
    def model_version(self) -> str:
        return MODEL_VERSION

    async def estimate(self, listing: Listing, features: CollectionFeatures) -> FairPriceEstimate:
        components = [estimate_floor(features)]
        comparable = estimate_comparable(features)
        if comparable is not None:
            components.append(comparable)
        trait = estimate_traits(listing.item, features)
        if trait is not None:
            components.append(trait)

        return self._combine(components, features)

    def _combine(
        self,
        components: Sequence[ModelEstimate],
        features: CollectionFeatures,
    ) -> FairPriceEstimate:
        total_weight = sum((component.weight for component in components), start=Decimal(0))

        # ── точечная оценка: взвешенное среднее компонент ───────────────
        blended = (
            sum(
                (component.value.ton * component.weight for component in components),
                start=Decimal(0),
            )
            / total_weight
        )

        multiplier, momentum_weight, momentum_explanation = momentum_adjustment(features)

        value = _ton(blended * multiplier)

        # ── интервал: P25/P75 точечных оценок (±10% при одной компоненте) ─
        values = [component.value for component in components]
        if len(values) >= _MIN_INTERVAL_POINTS:
            lower = _ton(_nearest_rank(values, Decimal("25")).ton * multiplier)
            upper = _ton(_nearest_rank(values, Decimal("75")).ton * multiplier)
        else:
            lower = _ton(blended * Decimal("0.90") * multiplier)
            upper = _ton(blended * Decimal("1.10") * multiplier)
        # квантование не должно нарушить инвариант lower <= value <= upper
        lower = min(lower, value)
        upper = max(upper, value)

        # ── confidence: покрытие × согласие ─────────────────────────────
        coverage = clamp((total_weight + momentum_weight) / Decimal(1), Decimal(0), Decimal(1))
        dispersion = _dispersion(values, blended)
        agreement = clamp(Decimal(1) - dispersion, _AGREEMENT_FLOOR, Decimal(1))
        confidence = clamp(coverage * agreement, Decimal(0), Decimal(1))

        explanation = [
            *[part for component in components for part in component.explanation],
        ]
        if momentum_explanation is not None:
            explanation.append(momentum_explanation)
        explanation.append(
            f"Ансамбль {len(components)} моделей: fair ≈ {value.formatted} TON, "
            f"интервал {lower.formatted}–{upper.formatted} TON"
        )

        return FairPriceEstimate(
            value=value,
            confidence=confidence,
            method=EstimationMethod.ENSEMBLE,
            lower_bound=lower,
            upper_bound=upper,
            sample_size=max((component.sample_size for component in components), default=0),
            explanation=tuple(explanation),
            model_version=MODEL_VERSION,
        )


def _dispersion(values: Sequence[TONAmount], blended: Decimal) -> Decimal:
    """Относительный разброс точечных оценок: (max - min) / blended, 0..1."""
    if len(values) < _MIN_INTERVAL_POINTS or blended <= 0:
        return Decimal(0)
    span = max(values).ton - min(values).ton
    return clamp(span / blended, Decimal(0), Decimal(1))
