"""Деньги: TON / nanoTON / USD (ядро).

Правила из ТЗ:
- TON — всегда Decimal (9 знаков после точки, = nanoTON в int);
- USD — Decimal; курс TON/USD — Decimal;
- float запрещён на уровне линтера (scripts/no_float.py, shared/ вне whitelist);
- все value objects иммутабельны.

Семантика:
- ``TONAmount`` — сумма TON. Строго: не больше 9 знаков дробной части.
- ``USDAmount`` — сумма USD (произвольная точность, форматирование — до 2).
- ``USDRate`` — курс «1 TON = X USD», строго положительный.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from functools import total_ordering

NANO_PER_TON: int = 1_000_000_000
_TON_QUANTUM = Decimal("0.000000001")  # 1 nanoTON
_MICROS = Decimal("0.000001")
_CENTS = Decimal("0.01")


class MoneyError(ValueError):
    """Некорректное денежное значение или операция."""


def format_ton(nano: int) -> str:
    """nanoTON → строка TON без хвостовых нулей: 120_000_000_000 → "120", 0 → "0"."""
    if nano < 0:
        msg = "nanoTON не может быть отрицательным"
        raise ValueError(msg)
    value = (Decimal(nano) / Decimal(NANO_PER_TON)).quantize(_MICROS, rounding=ROUND_HALF_UP)
    return _trim(value)


def format_usd(usd: Decimal) -> str:
    """Decimal USD → строка с 2 знаками: ``$580.12``."""
    value = usd.quantize(_CENTS, rounding=ROUND_HALF_UP)
    return f"${value:f}"


def _trim(value: Decimal) -> str:
    text = f"{value:f}"
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text


def _to_decimal(value: Decimal | int, what: str) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, (Decimal, int)):
        msg = f"{what}: ожидается Decimal или int (float запрещён), получено {type(value).__name__}"
        raise MoneyError(msg)
    return value if isinstance(value, Decimal) else Decimal(value)


@total_ordering
@dataclass(frozen=True, slots=True)
class TONAmount:
    """Сумма TON. Хранится как Decimal с точностью до nanoTON (9 знаков)."""

    ton: Decimal

    def __post_init__(self) -> None:
        ton = _to_decimal(self.ton, "TONAmount")
        if ton != ton.quantize(_TON_QUANTUM):
            msg = f"TON: не более 9 знаков дробной части, получено {ton}"
            raise MoneyError(msg)
        object.__setattr__(self, "ton", ton)

    # ── конструкторы ────────────────────────────────────────────────────

    @classmethod
    def from_ton(cls, value: Decimal | int) -> TONAmount:
        return cls(ton=_to_decimal(value, "TONAmount"))

    @classmethod
    def from_nano(cls, nano: int) -> TONAmount:
        if isinstance(nano, bool) or not isinstance(nano, int):
            msg = f"nano: ожидается int, получено {type(nano).__name__}"
            raise MoneyError(msg)
        return cls(ton=Decimal(nano) / Decimal(NANO_PER_TON))

    @classmethod
    def zero(cls) -> TONAmount:
        return cls(ton=Decimal(0))

    # ── свойства ────────────────────────────────────────────────────────

    @property
    def nano(self) -> int:
        return int((self.ton * Decimal(NANO_PER_TON)).to_integral_value())

    @property
    def is_zero(self) -> bool:
        return self.ton == 0

    @property
    def is_negative(self) -> bool:
        return self.ton < 0

    @property
    def formatted(self) -> str:
        """Человекочитаемо: "120", "0.5", "-3.25"."""
        return _trim(self.ton)

    # ── арифметика ──────────────────────────────────────────────────────

    def __lt__(self, other: object) -> bool:
        if not isinstance(other, TONAmount):
            return NotImplemented
        return self.ton < other.ton

    def add(self, other: TONAmount) -> TONAmount:
        return TONAmount(ton=self.ton + other.ton)

    def sub(self, other: TONAmount) -> TONAmount:
        return TONAmount(ton=self.ton - other.ton)

    def __add__(self, other: TONAmount) -> TONAmount:
        return self.add(other)

    def __sub__(self, other: TONAmount) -> TONAmount:
        return self.sub(other)

    def __neg__(self) -> TONAmount:
        return TONAmount(ton=-self.ton)

    def scale(self, factor: Decimal | int) -> TONAmount:
        """Умножение на коэффициент Decimal (например, вес модели)."""
        f = _to_decimal(factor, "factor")
        return TONAmount(ton=(self.ton * f).quantize(_TON_QUANTUM, rounding=ROUND_HALF_UP))

    def abs(self) -> TONAmount:
        return TONAmount(ton=abs(self.ton))

    def require_non_negative(self) -> TONAmount:
        if self.ton < 0:
            msg = f"сумма не может быть отрицательной: {self.ton} TON"
            raise MoneyError(msg)
        return self

    # ── конверсии ───────────────────────────────────────────────────────

    def to_usd(self, rate: USDRate) -> USDAmount:
        return USDAmount(usd=self.ton * rate.usd_per_ton)

    def to_nano_int(self) -> int:
        """Для границ (API/chain): nanoTON как int."""
        return self.nano


@total_ordering
@dataclass(frozen=True, slots=True)
class USDAmount:
    """Сумма USD (Decimal)."""

    usd: Decimal

    def __post_init__(self) -> None:
        object.__setattr__(self, "usd", _to_decimal(self.usd, "USDAmount"))

    @classmethod
    def from_usd(cls, value: Decimal | int) -> USDAmount:
        return cls(usd=_to_decimal(value, "USDAmount"))

    @classmethod
    def zero(cls) -> USDAmount:
        return cls(usd=Decimal(0))

    @property
    def formatted(self) -> str:
        return format_usd(self.usd)

    def __lt__(self, other: object) -> bool:
        if not isinstance(other, USDAmount):
            return NotImplemented
        return self.usd < other.usd

    def add(self, other: USDAmount) -> USDAmount:
        return USDAmount(usd=self.usd + other.usd)

    def sub(self, other: USDAmount) -> USDAmount:
        return USDAmount(usd=self.usd - other.usd)

    def __add__(self, other: USDAmount) -> USDAmount:
        return self.add(other)

    def __sub__(self, other: USDAmount) -> USDAmount:
        return self.sub(other)

    def to_ton(self, rate: USDRate) -> TONAmount:
        return TONAmount(
            ton=(self.usd / rate.usd_per_ton).quantize(_TON_QUANTUM, rounding=ROUND_HALF_UP)
        )


@dataclass(frozen=True, slots=True)
class USDRate:
    """Курс: 1 TON = ``usd_per_ton`` USD. Строго положительный."""

    usd_per_ton: Decimal

    def __post_init__(self) -> None:
        rate = _to_decimal(self.usd_per_ton, "USDRate")
        if rate <= 0:
            msg = "курс TON/USD должен быть положительным"
            raise MoneyError(msg)
        object.__setattr__(self, "usd_per_ton", rate)
