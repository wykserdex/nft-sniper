"""Алерт, решение пользователя и политика алертов (ТЗ §4, §7)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal

from nftsniper.contexts.valuation.domain.discount import Discount
from nftsniper.shared.domain.base import Entity, ValueObject
from nftsniper.shared.money import TONAmount


class DecisionAction:
    TAKEN = "taken"
    SKIPPED = "skipped"
    WATCH = "watch"
    MUTED = "muted"

    ALL = (TAKEN, SKIPPED, WATCH, MUTED)


@dataclass(frozen=True, slots=True)
class Alert(Entity):
    """Отправленный алерт (ТЗ §5: alerts). ``message_id`` — id сообщения
    в Telegram (после доставки)."""

    id: str
    user_id: str
    listing_id: str
    valuation_id: str
    dedup_key: str
    sent_at: datetime
    message_id: str | None = None

    def with_message_id(self, message_id: str) -> Alert:
        if self.message_id is not None:
            msg = "message_id уже установлен"
            raise ValueError(msg)
        return Alert(
            id=self.id,
            user_id=self.user_id,
            listing_id=self.listing_id,
            valuation_id=self.valuation_id,
            dedup_key=self.dedup_key,
            sent_at=self.sent_at,
            message_id=message_id,
        )


@dataclass(frozen=True, slots=True)
class Decision(Entity):
    """Решение пользователя по алерту (кнопка): действие + латентность (ТЗ §5)."""

    id: str
    alert_id: str
    user_id: str
    action: str
    latency_ms: int
    created_at: datetime

    def __post_init__(self) -> None:
        if self.action not in DecisionAction.ALL:
            msg = f"неизвестное действие: {self.action}"
            raise ValueError(msg)
        if self.latency_ms < 0:
            msg = "latency_ms не может быть отрицательным"
            raise ValueError(msg)


@dataclass(frozen=True, slots=True)
class AlertButton(ValueObject):
    """Кнопка inline-клавиатуры."""

    text: str
    callback_data: str


@dataclass(frozen=True, slots=True)
class AlertMessage(ValueObject):
    """Собранное сообщение алерта (текст + кнопки) для NotifierPort."""

    text: str
    buttons: tuple[AlertButton, ...] = ()


@dataclass(frozen=True, slots=True)
class AlertPolicy(ValueObject):
    """Пороги пользователя (ТЗ §4: условия отправки алерта)."""

    min_discount: Decimal  # >= 0, например 0.25
    min_confidence: Decimal  # >= 0.5
    price_min: TONAmount
    price_max: TONAmount
    min_liquidity: Decimal  # 0..1
    max_risk: Decimal  # 0..1
    dedup_window: timedelta = timedelta(hours=6)
    max_alerts_per_hour: int = 20

    def __post_init__(self) -> None:
        if self.min_discount < 0:
            msg = "min_discount не может быть отрицательным"
            raise ValueError(msg)
        if not (Decimal(0) <= self.min_confidence <= Decimal(1)):
            msg = "min_confidence должен быть в [0, 1]"
            raise ValueError(msg)
        if self.price_min > self.price_max:
            msg = "price_min > price_max"
            raise ValueError(msg)
        if not (Decimal(0) <= self.min_liquidity <= Decimal(1)):
            msg = "min_liquidity должен быть в [0, 1]"
            raise ValueError(msg)
        if not (Decimal(0) <= self.max_risk <= Decimal(1)):
            msg = "max_risk должен быть в [0, 1]"
            raise ValueError(msg)

    def allows(
        self,
        *,
        discount: Discount,
        confidence: Decimal,
        price: TONAmount,
        liquidity: Decimal,
        risk: Decimal,
    ) -> tuple[bool, tuple[str, ...]]:
        """Условия отправки алерта (ТЗ §4). Возвращает (разрешено, причины отказа)."""
        reasons: list[str] = []
        if not discount.meets_min(self.min_discount):
            reasons.append(f"discount {discount.pct} < порога {self.min_discount:.0%}")
        if confidence < self.min_confidence:
            reasons.append(f"confidence {confidence} < {self.min_confidence}")
        if not (self.price_min <= price <= self.price_max):
            reasons.append(
                f"цена {price.formatted} TON вне диапазона "
                f"[{self.price_min.formatted}, {self.price_max.formatted}]"
            )
        if liquidity < self.min_liquidity:
            reasons.append(f"liquidity {liquidity} < {self.min_liquidity}")
        if risk > self.max_risk:
            reasons.append(f"risk {risk} > {self.max_risk}")
        return (len(reasons) == 0, tuple(reasons))
