"""Floor-based модель (ТЗ §4).

Устойчивый floor как перцентиль P5 активных листингов, а не минимум: один
мусорный листинг не должен ронять floor. Перцентиль считает
(``CollectionFeatures.floor_p5``); здесь — оценка, границы и объяснение.

Интервал: ±10% вокруг floor; вес зависит от числа листингов (чем больше
выборка, тем надёжнее floor).
"""

from __future__ import annotations

from decimal import Decimal

from nftsniper.contexts.valuation.adapters.estimates import ModelEstimate, sample_quality
from nftsniper.contexts.valuation.domain.fair_price import CollectionFeatures

FLOOR_NOMINAL_WEIGHT = Decimal("0.30")
FLOOR_LISTINGS_FOR_FULL_QUALITY = 15
FLOOR_LOWER_FACTOR = Decimal("0.90")
FLOOR_UPPER_FACTOR = Decimal("1.10")


def estimate_floor(features: CollectionFeatures) -> ModelEstimate:
    """Floor-оценка из признаков коллекции (всегда доступна)."""
    listings = features.listings_count
    quality = sample_quality(listings, FLOOR_LISTINGS_FOR_FULL_QUALITY)
    floor = features.floor_p5
    return ModelEstimate(
        name="floor",
        value=floor,
        weight=FLOOR_NOMINAL_WEIGHT * quality,
        lower=floor.scale(FLOOR_LOWER_FACTOR),
        upper=floor.scale(FLOOR_UPPER_FACTOR),
        sample_size=listings,
        explanation=(f"Floor P5: {floor.formatted} TON по {listings} листингам",),
    )
