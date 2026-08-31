"""Доменные события контекста alerts (конвейер, ТЗ §6)."""

from dataclasses import dataclass

from nftsniper.shared.domain.base import DomainEvent


@dataclass(frozen=True, slots=True)
class AlertSent(DomainEvent):
    """Алерт доставлен пользователю."""

    alert_id: str
    user_id: str
    listing_id: str


@dataclass(frozen=True, slots=True)
class DecisionRecorded(DomainEvent):
    """Пользователь нажал кнопку по алерту."""

    alert_id: str
    user_id: str
    action: str
    latency_ms: int
