"""Общие типы моделей оценки.

``ModelEstimate`` — результат одной компоненты ансамбля: точечная оценка,
вес (уже с учётом качества данных), границы интервала и человекочитаемое
объяснение. Ансамбль комбинирует такие оценки во взвешенное среднее.

Все веса и коэффициенты — Decimal (без float, гейт no_float).
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from nftsniper.shared.money import TONAmount


@dataclass(frozen=True, slots=True)
class ModelEstimate:
    """Оценка одной компоненты ансамбля."""

    name: str
    value: TONAmount
    weight: Decimal  # 0..1, уже включает качество данных
    lower: TONAmount
    upper: TONAmount
    sample_size: int
    explanation: tuple[str, ...]


def sample_quality(sample_size: int, full_size: int) -> Decimal:
    """Качество данных по размеру выборки: ``min(1, sample / full)``, 0..1."""
    if full_size <= 0:
        msg = "full_size должен быть положительным"
        raise ValueError(msg)
    if sample_size >= full_size:
        return Decimal(1)
    if sample_size <= 0:
        return Decimal(0)
    return Decimal(sample_size) / Decimal(full_size)


def clamp(value: Decimal, low: Decimal, high: Decimal) -> Decimal:
    """Ограничить ``value`` диапазоном [low, high]."""
    return max(low, min(value, high))
