"""Алерт, решение пользователя и политика алертов (ТЗ §4, §7)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal

from nftsniper.contexts.valuation.domain.discount import Discount
from nftsniper.shared.domain.base import Entity, ValueObject
from nftsniper.shared.money import TONAmount

# Границы часа суток для quiet_hours (ТЗ §5).
_MIN_QUIET_HOUR = 0
_MAX_QUIET_HOUR = 23


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
    """Кнопка inline-клавиатуры.

    ``callback_data`` — для кнопок-решений; ``url`` — для кнопок-ссылок
    (диплинк на маркетплейс, ТЗ §1). Ровно одно из двух заполнено.
    """

    text: str
    callback_data: str | None = None
    url: str | None = None

    def __post_init__(self) -> None:
        if (self.callback_data is None) == (self.url is None):
            msg = "у кнопки должно быть ровно одно из: callback_data или url"
            raise ValueError(msg)


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
    quiet_hours: tuple[tuple[int, int], ...] = ()  # окна тишины (часы UTC), ТЗ §5

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
        for start, end in self.quiet_hours:
            if not (
                _MIN_QUIET_HOUR <= start <= _MAX_QUIET_HOUR
                and _MIN_QUIET_HOUR <= end <= _MAX_QUIET_HOUR
            ):
                msg = f"quiet_hours: часы должны быть в [0, 23], получено ({start}, {end})"
                raise ValueError(msg)
            if start == end:
                msg = "quiet_hours: начало и конец окна не могут совпадать"
                raise ValueError(msg)

    def is_quiet(self, now: datetime) -> bool:
        """Попал ли ``now`` в тихое время (часы — UTC, ТЗ §5).

        Окно может пересекать полночь: ``(22, 6)`` = 22:00–06:00.
        Локальный часовой пояс пользователя не учитывается (MVP: UTC).
        """
        hour = now.hour
        for start, end in self.quiet_hours:
            if start < end and start <= hour < end:
                return True
            if start > end and (hour >= start or hour < end):
                return True
        return False

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
