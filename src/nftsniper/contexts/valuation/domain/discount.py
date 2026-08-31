"""Дискаунт: насколько листинг дешевле fair price (ТЗ §4)."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

from nftsniper.shared.domain.base import ValueObject
from nftsniper.shared.money import TONAmount


class DiscountError(ValueError):
    """Некорректные аргументы расчёта дискаунта."""


@dataclass(frozen=True, slots=True)
class Discount(ValueObject):
    """``value = (fair - price) / fair``.

    Положительный — листинг дешевле fair (сделка); отрицательный — дороже.
    """

    value: Decimal  # (fair - price) / fair, полный знак
    fair_price: TONAmount
    listing_price: TONAmount

    def __post_init__(self) -> None:
        if self.fair_price <= TONAmount.zero():
            msg = "fair price должен быть положительным"
            raise DiscountError(msg)

    @classmethod
    def calculate(cls, fair_price: TONAmount, listing_price: TONAmount) -> Discount:
        if fair_price <= TONAmount.zero():
            msg = "fair price должен быть положительным"
            raise DiscountError(msg)
        if listing_price.is_negative:
            msg = "цена листинга не может быть отрицательной"
            raise DiscountError(msg)
        value = (fair_price.ton - listing_price.ton) / fair_price.ton
        return cls(value=value, fair_price=fair_price, listing_price=listing_price)

    # ── представления и проверки ────────────────────────────────────────

    @property
    def pct(self) -> str:
        """Процент в строку как в алерте (ТЗ §1): минус = скидка,
        т.е. ``-42%`` при fair 207 / цена 120; ``+12%`` — дороже fair."""
        if self.value == 0:
            return "0%"
        sign = "-" if self.value > 0 else "+"
        percent = abs(self.value * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
        return f"{sign}{int(percent)}%"

    def meets_min(self, min_discount: Decimal) -> bool:
        """discount >= порога пользователя (ТЗ §4)."""
        return self.value >= min_discount
