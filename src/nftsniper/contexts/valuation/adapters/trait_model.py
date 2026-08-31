"""Trait/rarity модель (ТЗ §4).

Прозрачная (объяснимая) rarity-модель: чем реже предмет, тем выше цена.
Сигнал редкости ``signal`` — 0..1 (1 = редкость):

- по трейтам: ``signal = 1 - min(trait.rarity)`` — редкость самого редкого
  трейта ведёт цену (``rarity`` — доля предметов с таким значением, ниже =
  реже);
- fallback: ``signal = 1 - item.rarity_rank`` (перцентиль, меньше = реже).

Множитель к базовой линии (median 7d, при отсутствии продаж — floor):
``1 + (signal - 0.5) * 2 * boost/penalty`` — при signal=1 множитель 1.5,
при signal=0 — 0.75, при 0.5 — 1.0. Всё на Decimal, без float.
"""

from __future__ import annotations

from decimal import Decimal

from nftsniper.contexts.sources.domain.item import Item
from nftsniper.contexts.valuation.adapters.comparable_sales import sales_7d_count
from nftsniper.contexts.valuation.adapters.estimates import ModelEstimate, sample_quality
from nftsniper.contexts.valuation.domain.fair_price import CollectionFeatures

TRAIT_NOMINAL_WEIGHT = Decimal("0.25")
TRAIT_MAX_BOOST = Decimal("0.50")  # редкий предмет: множитель до 1.5
TRAIT_MAX_PENALTY = Decimal("0.25")  # массовый предмет: множитель до 0.75
TRAIT_LOWER_FACTOR = Decimal("0.90")
TRAIT_UPPER_FACTOR = Decimal("1.10")
_RARITY_CENTER = Decimal("0.5")
_TWO = Decimal(2)


def rarity_signal(item: Item) -> Decimal | None:
    """Сигнал редкости 0..1; None, если данных о редкости нет."""
    trait_signals = [Decimal(1) - trait.rarity for trait in item.traits if trait.rarity is not None]
    if trait_signals:
        return max(trait_signals)
    if item.rarity_rank is not None:
        return Decimal(1) - item.rarity_rank
    return None


def rarity_multiplier(signal: Decimal) -> Decimal:
    """Сигнал редкости 0..1 → множитель цены [0.75, 1.5]."""
    if signal >= _RARITY_CENTER:
        return Decimal(1) + (signal - _RARITY_CENTER) * _TWO * TRAIT_MAX_BOOST
    return Decimal(1) - (_RARITY_CENTER - signal) * _TWO * TRAIT_MAX_PENALTY


def estimate_traits(item: Item, features: CollectionFeatures) -> ModelEstimate | None:
    """Trait-оценка; None, если данных о редкости нет."""
    signal = rarity_signal(item)
    if signal is None:
        return None

    traits_with_rarity = [trait for trait in item.traits if trait.rarity is not None]
    if traits_with_rarity:
        # покрытие = доля трейтов с известной редкостью
        coverage = sample_quality(len(traits_with_rarity), len(item.traits))
        sample_size = len(traits_with_rarity)
        basis = "редкость трейтов"
    else:
        coverage = Decimal(1)
        sample_size = 1
        basis = "rarity_rank"

    baseline = features.median_7d if _has_sales(features) else features.floor_p5
    multiplier = rarity_multiplier(signal)
    value = baseline.scale(multiplier)
    return ModelEstimate(
        name="trait",
        value=value,
        weight=TRAIT_NOMINAL_WEIGHT * coverage,
        lower=value.scale(TRAIT_LOWER_FACTOR),
        upper=value.scale(TRAIT_UPPER_FACTOR),
        sample_size=sample_size,
        explanation=(
            f"Trait-модель ({basis}): редкость {signal.quantize(Decimal('0.01'))} "
            f"→ ×{multiplier.quantize(Decimal('0.01'))} к baseline",
        ),
    )


def _has_sales(features: CollectionFeatures) -> bool:
    return sales_7d_count(features) > 0
