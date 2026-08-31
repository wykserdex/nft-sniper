"""Деньги: TON / nanoTON / USD —  (ядро), здесь — базовые примитивы.

Правила из ТЗ:
- TON — всегда Decimal; nanoTON — int; курс TON/USD — Decimal.
- float запрещён (статический гейт: scripts/no_float.py, shared/ вне whitelist).

Здесь появятся value objects TON/nanoTON/USD и арифметика с тестами.
"""

from decimal import ROUND_HALF_UP, Decimal

NANO_PER_TON: int = 1_000_000_000
_MICROS = Decimal("0.000001")


def format_ton(nano: int) -> str:
    """nanoTON → строка TON без хвостовых нулей: 120_000_000_000 → "120", 0 → "0"."""
    if nano < 0:
        msg = "nanoTON не может быть отрицательным"
        raise ValueError(msg)
    value = (Decimal(nano) / Decimal(NANO_PER_TON)).quantize(_MICROS, rounding=ROUND_HALF_UP)
    text = f"{value:f}"
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text
