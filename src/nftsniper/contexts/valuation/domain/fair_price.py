"""Оценка справедливой цены (ядро проекта, ТЗ §4)."""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import StrEnum

from nftsniper.shared.domain.base import ValueObject
from nftsniper.shared.money import TONAmount


class EstimationMethod(StrEnum):
    FLOOR_BASED = "floor_based"
    COMPARABLE_SALES = "comparable_sales"
    TRAIT_MODEL = "trait_model"
    MOMENTUM = "momentum"
    ENSEMBLE = "ensemble"


@dataclass(frozen=True, slots=True)
class FairPriceEstimate(ValueObject):
    """Результат оценки: ценность продукта.

    Правила из ТЗ §4 и §9:
    - confidence 0..1; без него оценка недействительна;
    - «никогда одну цифру»: lower/upper bound (25/75 перцентиль) обязательны;
    - explanation — человекочитаемые причины (показываются пользователю).
    """

    value: TONAmount
    confidence: Decimal  # 0..1
    method: EstimationMethod
    lower_bound: TONAmount
    upper_bound: TONAmount
    sample_size: int
    explanation: tuple[str, ...]
    model_version: str = "0.0.0"

    def __post_init__(self) -> None:
        if not (Decimal(0) <= self.confidence <= Decimal(1)):
            msg = f"confidence должен быть в [0, 1], получено {self.confidence}"
            raise ValueError(msg)
        if self.sample_size < 0:
            msg = "sample_size не может быть отрицательным"
            raise ValueError(msg)
        if self.lower_bound > self.value or self.value > self.upper_bound:
            msg = "оценка должна лежать в интервале [lower_bound, upper_bound]"
            raise ValueError(msg)

    def interval(self) -> tuple[TONAmount, TONAmount]:
        return self.lower_bound, self.upper_bound


@dataclass(frozen=True, slots=True)
class CollectionFeatures(ValueObject):
    """Признаки коллекции для модели оценки (заполняет)."""

    collection_id: str
    floor_p5: TONAmount  # устойчивый floor = P5 активных листингов (ТЗ §4)
    median_7d: TONAmount
    volume_24h: TONAmount
    sales_per_day: Decimal
    listings_count: int
    floor_24h_change: Decimal  # относительное изменение floor за 24h (например -0.03)
    floor_7d_change: Decimal
    as_of: datetime
    floor_history: tuple[Decimal, ...] = ()  # floor по дням (новые в конце)
    sales_7d: int = 0  # число продаж за 7 дней (для «Median 7d (N продаж)»)
