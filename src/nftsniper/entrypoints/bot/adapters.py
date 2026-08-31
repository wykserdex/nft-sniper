"""In-memory реализации портов бота (MVP, до).

В проде заменяются на Postgres/Redis-реализации: репозитории alerts и
таблица user_settings. Пока храним в памяти процесса — это тот же уровень,
что и in-memory адаптеры мини-аппа (wiring.py). Тесты используют эти же
классы.
"""

from __future__ import annotations

from nftsniper.contexts.alerts.domain.alert import Decision
from nftsniper.entrypoints.bot.domain import UserSettings


class InMemoryUserSettingsStore:
    def __init__(self) -> None:
        self._data: dict[str, UserSettings] = {}

    async def get(self, user_id: str) -> UserSettings | None:
        return self._data.get(user_id)

    async def save(self, settings: UserSettings) -> None:
        self._data[settings.user_id] = settings


class InMemoryWatchlistStore:
    def __init__(self) -> None:
        self._data: dict[str, list[str]] = {}

    async def add(self, user_id: str, item_id: str) -> None:
        items = self._data.setdefault(user_id, [])
        if item_id not in items:
            items.append(item_id)

    async def list(self, user_id: str) -> tuple[str, ...]:
        return tuple(self._data.get(user_id, []))


class InMemoryDecisionStore:
    def __init__(self) -> None:
        self._data: dict[str, list[Decision]] = {}
        self.saved: list[Decision] = []

    async def save(self, decision: Decision) -> None:
        self.saved.append(decision)
        self._data.setdefault(decision.user_id, []).append(decision)

    async def count_by_user(self, user_id: str) -> dict[str, int]:
        counts: dict[str, int] = {}
        for decision in self._data.get(user_id, []):
            counts[decision.action] = counts.get(decision.action, 0) + 1
        return counts


class InMemoryAlertRegistry:
    def __init__(self) -> None:
        self._data: dict[str, dict[str, object]] = {}

    async def get(self, alert_id: str) -> dict[str, object] | None:
        return self._data.get(alert_id)

    async def put(self, alert_id: str, context: dict[str, object]) -> None:
        self._data[alert_id] = context
