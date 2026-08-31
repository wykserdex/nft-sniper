"""AlertEngine: матчинг → дедуп → rate limit → quiet hours → доставка.

Приоритизация (ТЗ §7): кандидаты складываются в max-heap по приоритету
сделки, поэтому при потоке листингов первыми уходят лучшие. Очередь
ограничена бюджетами пользователей: на человека не более
``max_alerts_per_hour`` за час, поэтому всплеск 1000 листингов/мин не
превращается в 1000 алертов и не раздувает память (пер-пользовательский
top-K до попадания в очередь).
"""

from __future__ import annotations

import heapq
import uuid
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

from nftsniper.contexts.alerts.application.matcher import match_listing
from nftsniper.contexts.alerts.domain.alert import Alert, AlertMessage
from nftsniper.contexts.alerts.domain.candidate import (
    AlertCandidate,
    ListingScore,
    Subscriber,
)
from nftsniper.contexts.alerts.ports import (
    AlertRepository,
    NotifierPort,
    SubscriberDirectory,
)
from nftsniper.contexts.sources.application.clock import utcnow

_RATE_LIMIT_WINDOW = timedelta(hours=1)

Renderer = Callable[[AlertCandidate], AlertMessage]


class PrioritizedQueue:
    """Max-heap по приоритету: ``pop`` отдаёт лучшую сделку первой (ТЗ §7)."""

    def __init__(self) -> None:
        self._heap: list[tuple[Decimal, int, Any]] = []
        self._seq = 0

    def __len__(self) -> int:
        return len(self._heap)

    def push(self, priority: Decimal, item: Any) -> None:
        self._seq += 1
        heapq.heappush(self._heap, (-priority, self._seq, item))

    def pop(self) -> Any | None:
        if not self._heap:
            return None
        return heapq.heappop(self._heap)[2]


@dataclass(frozen=True, slots=True)
class DeliveryReport:
    """Итог прогона: сколько куда ушло и какие алерты отправлены."""

    matched: int
    sent: int
    deduped: int
    rate_limited: int
    quiet: int
    paused: int
    rejected: int
    alerts: tuple[Alert, ...]

    @property
    def skipped(self) -> int:
        """Все неотправленные кандидаты (кроме matched-отправленных)."""
        return self.deduped + self.rate_limited + self.quiet + self.paused + self.rejected


class AlertEngine:
    """Матчинг + дедупликация + rate limit + quiet hours + приоритизация."""

    def __init__(
        self,
        notifier: NotifierPort,
        alerts: AlertRepository,
        subscribers: SubscriberDirectory,
        renderer: Renderer,
        *,
        clock: Callable[[], datetime] = utcnow,
        id_factory: Callable[[], str] = lambda: uuid.uuid4().hex,
    ) -> None:
        self._notifier = notifier
        self._alerts = alerts
        self._subscribers = subscribers
        self._renderer = renderer
        self._clock = clock
        self._id_factory = id_factory

    async def deliver(self, score: ListingScore) -> DeliveryReport:
        """Доставить один оцененный листинг всем подходящим подписчикам."""
        return await self.deliver_batch((score,))

    async def deliver_batch(self, scores: Sequence[ListingScore]) -> DeliveryReport:
        now = self._clock()
        hour_ago = now - _RATE_LIMIT_WINDOW

        matched = 0
        paused = 0
        quiet = 0
        rejected = 0
        rate_limited = 0

        queue = PrioritizedQueue()
        policies: dict[str, Subscriber] = {}
        remaining: dict[str, int] = {}

        # Фаза 1: матчинг. Для каждого подписчика — не более бюджета
        # (max_alerts_per_hour минус уже отправленные за час) лучших кандидатов.
        for subscriber in await self._subscribers.list_subscribers():
            policies[subscriber.user_id] = subscriber
            if subscriber.paused:
                paused += len(scores)
                remaining[subscriber.user_id] = 0
                continue
            if subscriber.policy.is_quiet(now):
                quiet += len(scores)
                remaining[subscriber.user_id] = 0
                continue

            used = await self._alerts.count_recent(subscriber.user_id, hour_ago)
            budget = max(subscriber.policy.max_alerts_per_hour - used, 0)
            remaining[subscriber.user_id] = budget

            candidates: list[AlertCandidate] = []
            for score in scores:
                outcome = match_listing(score, subscriber, now=now, alert_id=self._id_factory())
                if outcome.allowed and outcome.candidate is not None:
                    matched += 1
                    candidates.append(outcome.candidate)
                elif outcome.reason == "rejected":
                    rejected += 1

            candidates.sort(key=lambda candidate: candidate.priority, reverse=True)
            rate_limited += max(len(candidates) - budget, 0)
            for candidate in candidates[:budget]:
                queue.push(candidate.priority, candidate)

        deduped, sent_alerts = await self._drain(queue, policies, remaining, now)

        return DeliveryReport(
            matched=matched,
            sent=len(sent_alerts),
            deduped=deduped,
            rate_limited=rate_limited,
            quiet=quiet,
            paused=paused,
            rejected=rejected,
            alerts=tuple(sent_alerts),
        )

    async def _drain(
        self,
        queue: PrioritizedQueue,
        policies: dict[str, Subscriber],
        remaining: dict[str, int],
        now: datetime,
    ) -> tuple[int, list[Alert]]:
        """Фаза 2: доставка по приоритету с дедупом и проверкой бюджета."""
        deduped = 0
        sent_alerts: list[Alert] = []
        while True:
            candidate = queue.pop()
            if candidate is None:
                break
            if remaining.get(candidate.user_id, 0) <= 0:
                continue
            dedup_window = policies[candidate.user_id].policy.dedup_window
            existing = await self._alerts.find_recent_by_dedup(
                candidate.user_id, candidate.dedup_key, now - dedup_window
            )
            if existing is not None:
                deduped += 1
                continue
            message_id = await self._notifier.send(candidate.user_id, self._renderer(candidate))
            alert = Alert(
                id=candidate.alert_id,
                user_id=candidate.user_id,
                listing_id=candidate.listing_id,
                valuation_id=candidate.valuation_id,
                dedup_key=candidate.dedup_key,
                sent_at=now,
                message_id=message_id,
            )
            await self._alerts.save(alert)
            sent_alerts.append(alert)
            remaining[candidate.user_id] -= 1
        return deduped, sent_alerts
