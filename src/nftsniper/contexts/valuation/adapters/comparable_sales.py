"""Comparable sales модель (ТЗ §4).

Медиана продаж похожих предметов за 7 дней с временным затуханием
(полураспад ~7 дней) — считает  (``CollectionFeatures.median_7d``).
Здесь — оценка, границы и объяснение.

Чем больше продаж за 7 дней, тем выше вес компоненты и уже интервал;
без продаж компонента недоступна (``None``).
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

from nftsniper.contexts.valuation.adapters.estimates import ModelEstimate, sample_quality
from nftsniper.contexts.valuation.domain.fair_price import CollectionFeatures

COMPARABLE_NOMINAL_WEIGHT = Decimal("0.35")
COMPARABLE_SALES_FOR_FULL_QUALITY = 8
COMPARABLE_BASE_SPREAD = Decimal("0.10")
COMPARABLE_EXTRA_SPREAD = Decimal("0.20")


def sales_7d_count(features: CollectionFeatures) -> int:
    """Число продаж за 7 дней, восстановленное из ``sales_per_day``."""
    count = (features.sales_per_day * Decimal(7)).to_integral_value(rounding=ROUND_HALF_UP)
    return int(count)


def estimate_comparable(features: CollectionFeatures) -> ModelEstimate | None:
    """Comparable-оценка; None, если продаж за 7 дней нет."""
    sales_count = sales_7d_count(features)
    if sales_count <= 0:
        return None
    quality = sample_quality(sales_count, COMPARABLE_SALES_FOR_FULL_QUALITY)
    median = features.median_7d
    # меньше данных → шире интервал (неопределённость честно отражается)
    spread = COMPARABLE_BASE_SPREAD + COMPARABLE_EXTRA_SPREAD * (Decimal(1) - quality)
    return ModelEstimate(
        name="comparable_sales",
        value=median,
        weight=COMPARABLE_NOMINAL_WEIGHT * quality,
        lower=median.scale(Decimal(1) - spread),
        upper=median.scale(Decimal(1) + spread),
        sample_size=sales_count,
        explanation=(
            f"Comparable sales: median 7d {median.formatted} TON по {sales_count} продажам",
        ),
    )
