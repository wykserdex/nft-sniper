"""TrackOutcome: трекинг исходов алертов через 1h/24h/7d (ТЗ §6).

Воркер outcome-tracker вызывает use case с актуальным состоянием листинга:
продался — фиксируется sold; иначе — цена в запрошенное окно. Первый снимок
создаёт ``Outcome`` с базовыми полями (цена алерта, fair price, дискаунт).
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from datetime import datetime
from decimal import Decimal

from nftsniper.contexts.alerts.domain.alert import Alert
from nftsniper.contexts.alerts.domain.outcome import Outcome, OutcomeWindow
from nftsniper.contexts.alerts.ports import OutcomeRepository
from nftsniper.contexts.sources.application.clock import utcnow
from nftsniper.contexts.sources.domain.listing import Listing, ListingStatus
from nftsniper.shared.money import TONAmount


class TrackOutcome:
    """Зафиксировать состояние листинга в окне (1h/24h/7d) или продажу."""

    def __init__(
        self,
        outcomes: OutcomeRepository,
        *,
        clock: Callable[[], datetime] = utcnow,
        id_factory: Callable[[], str] = lambda: uuid.uuid4().hex,
    ) -> None:
        self._outcomes = outcomes
        self._clock = clock
        self._id_factory = id_factory

    async def run(
        self,
        *,
        alert: Alert,
        listing: Listing,
        fair_price: TONAmount,
        discount: Decimal,
        window: OutcomeWindow,
    ) -> Outcome:
        now = self._clock()
        outcome = await self._outcomes.get_by_alert(alert.id)
        if outcome is None:
            outcome = Outcome(
                id=self._id_factory(),
                alert_id=alert.id,
                user_id=alert.user_id,
                listing_id=alert.listing_id,
                alert_price=listing.price,
                fair_price=fair_price,
                discount=discount,
                computed_at=now,
            )
        if listing.status is ListingStatus.SOLD:
            outcome = outcome.mark_sold(
                sold_at=listing.closed_at if listing.closed_at is not None else now,
                sold_price=listing.price,
                at=now,
            )
        else:
            outcome = outcome.apply_snapshot(window=window, price=listing.price, at=now)
        await self._outcomes.save(outcome)
        return outcome
