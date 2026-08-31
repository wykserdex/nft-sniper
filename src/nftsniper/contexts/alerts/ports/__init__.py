"""Порты контекста alerts: NotifierPort, репозитории, каталог подписчиков.

Алерт-движок зависит только от этих протоколов: доставка
(NotifierPort), хранение алертов, решений и исходов (репозитории), список
подписчиков с настройками (SubscriberDirectory). Аналитика читает
те же репозитории: alerts/outcomes/decisions по пользователю.
"""

from collections.abc import Sequence
from datetime import datetime
from typing import Protocol

from nftsniper.contexts.alerts.domain.alert import Alert, AlertMessage, Decision
from nftsniper.contexts.alerts.domain.candidate import Subscriber
from nftsniper.contexts.alerts.domain.outcome import Outcome


class NotifierPort(Protocol):
    """Доставка алертов (адаптер — Telegram, aiogram;)."""

    async def send(self, user_id: str, message: AlertMessage) -> str:
        """Отправить, вернуть message_id (для последующего редактирования)."""
        ...

    async def edit(self, user_id: str, message_id: str, message: AlertMessage) -> None:
        """Редактировать сообщение после решения (ТЗ §6)."""
        ...


class AlertRepository(Protocol):
    async def save(self, alert: Alert) -> None: ...

    async def get(self, alert_id: str) -> Alert | None: ...

    async def list_by_user(self, user_id: str) -> Sequence[Alert]:
        """Все алерты пользователя (для аналитики)."""
        ...

    async def list_recent(self, since: datetime) -> Sequence[Alert]:
        """Алерты с ``since`` по всем пользователям (трекинг исходов)."""
        ...

    async def find_recent_by_dedup(
        self, user_id: str, dedup_key: str, since_ts: datetime
    ) -> Alert | None:
        """Дедупликация: алерт с тем же ключом в окне дедупа (ТЗ §6)."""
        ...

    async def count_recent(self, user_id: str, since: datetime) -> int:
        """Сколько алертов отправлено пользователю с ``since`` (rate limit)."""
        ...


class DecisionRepository(Protocol):
    async def save(self, decision: Decision) -> None: ...

    async def list_by_alert(self, alert_id: str) -> list[Decision]: ...

    async def list_by_user(self, user_id: str) -> list[Decision]:
        """Все решения пользователя (для аналитики)."""
        ...


class OutcomeRepository(Protocol):
    """Исходы алертов (таблица ``outcomes``, ТЗ §5;)."""

    async def save(self, outcome: Outcome) -> None: ...

    async def get_by_alert(self, alert_id: str) -> Outcome | None: ...

    async def list_by_user(self, user_id: str) -> Sequence[Outcome]: ...


class SubscriberDirectory(Protocol):
    """Список подписчиков с настройками для матчинга."""

    async def list_subscribers(self) -> Sequence[Subscriber]:
        """Все подписчики (user_id + AlertPolicy + язык + пауза)."""
        ...
