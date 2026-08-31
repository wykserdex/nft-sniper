"""Риск и анти-скам (ТЗ §4): RiskFlag, RiskScore.

Логика детекции —; здесь — контракты значений, которыми
пользуются valuation/alerts/risk-адаптеры.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from nftsniper.shared.domain.base import ValueObject


class RiskSeverity:
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"

    ALL = (LOW, MEDIUM, HIGH)


_SEVERITY_VALUES: dict[str, Decimal] = {
    RiskSeverity.LOW: Decimal("0.2"),
    RiskSeverity.MEDIUM: Decimal("0.5"),
    RiskSeverity.HIGH: Decimal("0.9"),
}


@dataclass(frozen=True, slots=True)
class RiskFlag(ValueObject):
    """Признак риска с человекочитаемым сообщением (показывается в UI).

    Коды (согласованный набор,  расширяет):
    FRESH_SELLER, WASH_TRADING, CLONE_COLLECTION, LOW_VOLUME,
    BROKEN_METADATA, FAKE_SALES, AUCTION_MISMATCH, PRICE_DISCREPANCY,
    ROYALTY_IMPACT, UNKNOWN_SELLER.
    """

    code: str
    severity: str
    message: str

    def __post_init__(self) -> None:
        if self.severity not in RiskSeverity.ALL:
            msg = f"неизвестная severity: {self.severity}"
            raise ValueError(msg)

    @property
    def value(self) -> Decimal:
        return _SEVERITY_VALUES[self.severity]


@dataclass(frozen=True, slots=True)
class RiskScore(ValueObject):
    """Сводный риск (0..1) + список флагов.

    ``value`` — агрегат (вычисляет); при добавлении флага
    итог не может быть ниже базовой severity флага.
    """

    value: Decimal
    flags: tuple[RiskFlag, ...] = ()

    def __post_init__(self) -> None:
        if not (Decimal(0) <= self.value <= Decimal(1)):
            msg = f"risk score должен быть в [0, 1], получено {self.value}"
            raise ValueError(msg)

    @classmethod
    def clean(cls) -> RiskScore:
        return cls(value=Decimal(0), flags=())

    def with_flag(self, flag: RiskFlag) -> RiskScore:
        value = max(self.value, flag.value)
        return RiskScore(value=value, flags=(*self.flags, flag))

    @property
    def worst_severity(self) -> str | None:
        if not self.flags:
            return None
        order = {RiskSeverity.LOW: 0, RiskSeverity.MEDIUM: 1, RiskSeverity.HIGH: 2}
        return max(self.flags, key=lambda f: order[f.severity]).severity

    def passes(self, max_score: Decimal) -> bool:
        """risk_score <= порога (ТЗ §4)."""
        return self.value <= max_score
