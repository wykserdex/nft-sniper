"""Порты контекста alerts: NotifierPort, репозитории (Алерт-движок —)."""

from typing import Protocol

from nftsniper.contexts.alerts.domain.alert import Alert, AlertMessage, Decision


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

    async def find_recent_by_dedup(
        self, user_id: str, dedup_key: str, since_ts: object
    ) -> Alert | None:
        """Дедупликация: алерт с тем же ключом в окне дедупа (ТЗ §6)."""
        ...


class DecisionRepository(Protocol):
    async def save(self, decision: Decision) -> None: ...

    async def list_by_alert(self, alert_id: str) -> list[Decision]: ...
