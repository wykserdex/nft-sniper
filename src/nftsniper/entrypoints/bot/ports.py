"""Порты бота: хранилища и логгер интентов.

Все реализации подменяемы: в проде — Postgres/Redis, в тестах —
in-memory fake'и. Бот не знает о конкретной реализации.
"""

from typing import Protocol

from nftsniper.contexts.alerts.domain.alert import Decision
from nftsniper.entrypoints.bot.domain import UserSettings


class UserSettingsStore(Protocol):
    async def get(self, user_id: str) -> UserSettings | None: ...

    async def save(self, settings: UserSettings) -> None: ...

    async def list_users(self) -> tuple[str, ...]:
        """Все user_id с сохранёнными настройками (для матчинга)."""
        ...


class WatchlistStore(Protocol):
    """Вотчлист: user_id → адреса предметов."""

    async def add(self, user_id: str, item_id: str) -> None: ...

    async def list(self, user_id: str) -> tuple[str, ...]: ...


class DecisionStore(Protocol):
    """Запись решений пользователя (decisions, ТЗ §5; использует)."""

    async def save(self, decision: Decision) -> None: ...

    async def count_by_user(self, user_id: str) -> dict[str, int]:
        """Счётчики действий: {taken, skipped, watch, muted}."""
        ...


class AlertRegistry(Protocol):
    """Alert_id → контекст алерта (для диплинков, вотчлиста, мьюта).

    Нужен, потому что callback_data ограничен 64 байтами: в кнопке лежит
    только короткий alert_id, а адреса предмета/коллекции бот достаёт отсюда.
    """

    async def get(self, alert_id: str) -> dict[str, object] | None: ...

    async def put(self, alert_id: str, context: dict[str, object]) -> None: ...
