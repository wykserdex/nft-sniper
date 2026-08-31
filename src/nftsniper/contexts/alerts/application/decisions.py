"""RecordDecision: запись решения пользователя + доменное событие.

Каноническая точка записи решений (ТЗ §6): save в DecisionRepository и
``DecisionRecorded`` для калибровки модели. ``BotService``
 может делегировать сюда; до этого — дублирует логику записи.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from nftsniper.contexts.alerts.domain.alert import Decision
from nftsniper.contexts.alerts.domain.events import DecisionRecorded
from nftsniper.contexts.alerts.ports import DecisionRepository
from nftsniper.contexts.sources.application.clock import utcnow


@dataclass(frozen=True, slots=True)
class RecordDecisionResult:
    """Решение + событие для калибровки."""

    decision: Decision
    event: DecisionRecorded


class RecordDecision:
    """Записать решение по алерту (кнопка «Взять/Скип/Следить/Мьют»)."""

    def __init__(
        self,
        decisions: DecisionRepository,
        *,
        clock: Callable[[], datetime] = utcnow,
        id_factory: Callable[[], str] = lambda: uuid.uuid4().hex,
    ) -> None:
        self._decisions = decisions
        self._clock = clock
        self._id_factory = id_factory

    async def run(
        self,
        *,
        alert_id: str,
        user_id: str,
        action: str,
        latency_ms: int,
    ) -> RecordDecisionResult:
        created_at = self._clock()
        decision = Decision(
            id=self._id_factory(),
            alert_id=alert_id,
            user_id=user_id,
            action=action,
            latency_ms=latency_ms,
            created_at=created_at,
        )
        await self._decisions.save(decision)
        event = DecisionRecorded(
            occurred_at=created_at,
            alert_id=alert_id,
            user_id=user_id,
            action=action,
            latency_ms=latency_ms,
        )
        return RecordDecisionResult(decision=decision, event=event)
