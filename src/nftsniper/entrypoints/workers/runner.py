"""Воркеры: цикл конвейера, трекинг исходов, калибратор.

- ``run_pipeline_loop`` — цикл poll → score → risk → notify с метриками;
- ``OutcomeTracker`` — снимки исходов по окнам 1h/24h/7d (ТЗ §6);
- ``run_calibrator_once`` — рекомендации порогов per-user.

Все три — поверх портов/use cases, без прямого I/O: тестируются на fake'ах.
Время (``clock``) и sleep инжектируются, чтобы цикл был детерминированным.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal

from nftsniper.contexts.alerts.application.analytics import (
    DEFAULT_TARGET_PRECISION,
    AlertAnalytics,
)
from nftsniper.contexts.alerts.application.outcome_tracking import TrackOutcome
from nftsniper.contexts.alerts.domain.outcome import Outcome, OutcomeWindow
from nftsniper.contexts.alerts.ports import (
    AlertRepository,
    OutcomeRepository,
    SubscriberDirectory,
)
from nftsniper.contexts.sources.application.clock import utcnow
from nftsniper.contexts.sources.ports.repositories import ListingRepository
from nftsniper.contexts.valuation.domain.discount import Discount
from nftsniper.contexts.valuation.ports import ValuationRepository
from nftsniper.entrypoints.workers.pipeline import PipelineReport
from nftsniper.observability import metrics
from nftsniper.observability.logging import get_logger

logger = get_logger(__name__)

Poll = Callable[[], Awaitable[PipelineReport]]
Sleep = Callable[[int], Awaitable[None]]

OUTCOME_WINDOWS: tuple[tuple[OutcomeWindow, timedelta], ...] = (
    (OutcomeWindow.ONE_HOUR, timedelta(hours=1)),
    (OutcomeWindow.TWENTY_FOUR_HOURS, timedelta(hours=24)),
    (OutcomeWindow.SEVEN_DAYS, timedelta(days=7)),
)

# Насколько далеко в прошлое заглядывает трекер исходов (7d + запас).
_OUTCOME_LOOKBACK = timedelta(days=8)


async def _sleep(seconds: int) -> None:
    await asyncio.sleep(seconds)


async def run_pipeline_loop(
    poll: Poll,
    *,
    cycles: int | None = None,
    poll_interval_seconds: int = 3,
    sleep: Sleep = _sleep,
) -> list[PipelineReport]:
    """Гонять конвейер по расписанию (poller 2–5 сек, ТЗ §6).

    ``cycles=None`` — бесконечно (для CLI); в тестах — конечное число циклов
    с фиктивным sleep. Каждый цикл пишет метрики: ingested/sent/dropped и
    latency этапа poller.
    """
    reports: list[PipelineReport] = []
    counter = 0
    while cycles is None or counter < cycles:
        started = time.monotonic()
        try:
            report = await poll()
            reports.append(report)
            metrics.listings_ingested_total.inc(report.discovered)
            metrics.alerts_sent_total.inc(report.delivered)
            metrics.alerts_dropped_total.inc(report.dropped)
        except Exception:
            logger.exception("pipeline_cycle_failed")
        metrics.observe_stage("poller", time.monotonic() - started)
        counter += 1
        if cycles is not None and counter >= cycles:
            break
        await sleep(poll_interval_seconds)
    return reports


def _window_recorded(outcome: Outcome | None, window: OutcomeWindow) -> bool:
    if outcome is None:
        return False
    if outcome.sold_price is not None:
        return True  # продан — окна закрыты
    if window is OutcomeWindow.ONE_HOUR:
        return outcome.price_after_1h is not None
    if window is OutcomeWindow.TWENTY_FOUR_HOURS:
        return outcome.price_after_24h is not None
    return outcome.price_after_7d is not None


class OutcomeTracker:
    """Трекинг исходов через 1h/24h/7d (ТЗ §6: Outcome tracker)."""

    def __init__(
        self,
        *,
        alerts: AlertRepository,
        outcomes: OutcomeRepository,
        listings: ListingRepository,
        valuations: ValuationRepository,
        track: TrackOutcome,
        clock: Callable[[], datetime] = utcnow,
    ) -> None:
        self._alerts = alerts
        self._outcomes = outcomes
        self._listings = listings
        self._valuations = valuations
        self._track = track
        self._clock = clock

    async def run_once(self) -> int:
        """Снять снимки по всем наступившим окнам; вернуть число записей."""
        now = self._clock()
        recent = await self._alerts.list_recent(now - _OUTCOME_LOOKBACK)
        recorded = 0
        for window, age in OUTCOME_WINDOWS:
            cutoff = now - age
            for alert in recent:
                if alert.sent_at > cutoff:
                    continue  # окно ещё не наступило
                existing = await self._outcomes.get_by_alert(alert.id)
                if _window_recorded(existing, window):
                    continue
                listing = await self._listings.get(alert.listing_id)
                if listing is None:
                    continue
                estimate = await self._valuations.get_by_listing(alert.listing_id)
                if estimate is None:
                    continue
                discount = Discount.calculate(estimate.value, listing.price).value
                await self._track.run(
                    alert=alert,
                    listing=listing,
                    fair_price=estimate.value,
                    discount=discount,
                    window=window,
                )
                recorded += 1
        return recorded


@dataclass(frozen=True, slots=True)
class CalibrationRecommendation:
    """Рекомендация порога min_discount для пользователя (калибратор)."""

    user_id: str
    current: Decimal
    recommended: Decimal
    precision: Decimal | None
    sample_size: int


async def run_calibrator_once(
    *,
    subscribers: SubscriberDirectory,
    analytics: AlertAnalytics,
    target_precision: Decimal = DEFAULT_TARGET_PRECISION,
) -> tuple[CalibrationRecommendation, ...]:
    """Ночной калибратор: рекомендации порогов per-user (ТЗ §6)."""
    recommendations: list[CalibrationRecommendation] = []
    for subscriber in await subscribers.list_subscribers():
        rec = await analytics.recommend(
            subscriber.user_id,
            current=subscriber.policy.min_discount,
            target_precision=target_precision,
        )
        if rec.recommended != rec.current:
            recommendations.append(
                CalibrationRecommendation(
                    user_id=subscriber.user_id,
                    current=rec.current,
                    recommended=rec.recommended,
                    precision=rec.precision,
                    sample_size=rec.sample_size,
                )
            )
            logger.info(
                "calibration_recommendation",
                user_id=subscriber.user_id,
                current=str(rec.current),
                recommended=str(rec.recommended),
                precision=str(rec.precision) if rec.precision is not None else None,
            )
    return tuple(recommendations)
