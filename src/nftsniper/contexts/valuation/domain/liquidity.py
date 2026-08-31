"""Ликвидность: продаваемость важнее самой скидки (ТЗ §4)."""

from dataclasses import dataclass
from decimal import Decimal

from nftsniper.shared.domain.base import ValueObject


@dataclass(frozen=True, slots=True)
class LiquidityScore(ValueObject):
    """Нормированный скор ликвидности (0..1).

    Вычисляется в  (sales_per_day, объёмы); use cases
    используют только ``value`` и ``meets_min``.
    """

    value: Decimal  # 0..1
    sales_per_day: Decimal
    basis: str  # описание расчёта (аудит)

    def __post_init__(self) -> None:
        if not (Decimal(0) <= self.value <= Decimal(1)):
            msg = f"liquidity value должен быть в [0, 1], получено {self.value}"
            raise ValueError(msg)

    def meets_min(self, min_liquidity: Decimal) -> bool:
        return self.value >= min_liquidity
