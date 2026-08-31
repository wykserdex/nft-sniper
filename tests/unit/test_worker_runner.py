"""Воркеры: цикл конвейера, трекер исходов, калибратор."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from nftsniper.contexts.alerts.application.analytics import AlertAnalytics
from nftsniper.contexts.alerts.application.outcome_tracking import TrackOutcome
from nftsniper.contexts.alerts.domain.alert import Alert, AlertPolicy
from nftsniper.contexts.alerts.domain.candidate import Subscriber
from nftsniper.contexts.alerts.domain.outcome import Outcome
from nftsniper.contexts.sources.domain.item import Item
from nftsniper.contexts.sources.domain.listing import Listing
from nftsniper.contexts.sources.domain.marketplace import Marketplace
from nftsniper.contexts.valuation.domain.fair_price import (
    EstimationMethod,
    FairPriceEstimate,
)
from nftsniper.entrypoints.workers.pipeline import PipelineReport
from nftsniper.entrypoints.workers.runner import (
    OutcomeTracker,
    run_calibrator_once,
    run_pipeline_loop,
)
from nftsniper.shared.money import TONAmount
from nftsniper.shared.ton_address import TonAddress
from tests.fakes import (
    FakeSubscriberDirectory,
    InMemoryAlertRepository,
    InMemoryDecisionRepository,
    InMemoryListingRepository,
    InMemoryOutcomeRepository,
    InMemoryValuationRepository,
)

D = Decimal
NOW = datetime(2026, 8, 31, 12, 0, 0, tzinfo=UTC)
COLL = "EQChoaGhoaGhoaGhoaGhoaGhoaGhoaGhoaGhoaGhoaGhodWi"
SELLER = TonAddress(workchain=0, raw_bytes=bytes([0xD1]) * 32)


def _listing(price: str = "120") -> Listing:
    item = Item(id="EQItem1", collection_id=COLL, index=1, name="#1")
    return Listing(
        id="getgems:lg-1",
        external_id="lg-1",
        marketplace=Marketplace.GETGEMS,
        item=item,
        price=TONAmount.from_ton(D(price)),
        seller=SELLER,
        listed_at=NOW,
    )


def _estimate(value: str = "207") -> FairPriceEstimate:
    price = TONAmount.from_ton(D(value))
    return FairPriceEstimate(
        value=price,
        confidence=D("0.7"),
        method=EstimationMethod.ENSEMBLE,
        lower_bound=price,
        upper_bound=price,
        sample_size=10,
        explanation=("ансамбль",),
        model_version="7.0.0",
    )


# ── цикл конвейера ───────────────────────────────────────────────────────


async def test_pipeline_loop_runs_cycles() -> None:
    calls: list[int] = []
    sleeps: list[int] = []

    async def poll() -> PipelineReport:
        calls.append(1)
        return PipelineReport(
            discovered=1, scored=1, risk_flagged=0, matched=1, delivered=1, dropped=0
        )

    async def fake_sleep(seconds: int) -> None:
        sleeps.append(seconds)

    reports = await run_pipeline_loop(poll, cycles=3, poll_interval_seconds=2, sleep=fake_sleep)
    assert len(reports) == 3
    assert len(calls) == 3
    assert sleeps == [2, 2]  # после последнего цикла не спим


async def test_pipeline_loop_survives_errors() -> None:
    counter = {"n": 0}

    async def poll() -> PipelineReport:
        counter["n"] += 1
        if counter["n"] == 1:
            msg = "источник недоступен"
            raise RuntimeError(msg)
        return PipelineReport(0, 0, 0, 0, 0, 0)

    reports = await run_pipeline_loop(poll, cycles=2, poll_interval_seconds=0)
    assert len(reports) == 1  # один успешный цикл


# ── трекер исходов ───────────────────────────────────────────────────────


async def test_outcome_tracker_records_due_windows() -> None:
    alerts = InMemoryAlertRepository()
    outcomes = InMemoryOutcomeRepository()
    listings = InMemoryListingRepository()
    valuations = InMemoryValuationRepository()

    await listings.save(_listing("125"))
    await valuations.save("getgems:lg-1", _estimate("200"))

    await alerts.save(
        Alert(
            id="al-1",
            user_id="u1",
            listing_id="getgems:lg-1",
            valuation_id="v-1",
            dedup_key="getgems:lg-1",
            sent_at=NOW - timedelta(hours=2),
        )
    )
    await alerts.save(
        Alert(
            id="al-2",
            user_id="u1",
            listing_id="getgems:lg-1",
            valuation_id="v-2",
            dedup_key="getgems:lg-1",
            sent_at=NOW - timedelta(minutes=30),
        )
    )

    tracker = OutcomeTracker(
        alerts=alerts,
        outcomes=outcomes,
        listings=listings,
        valuations=valuations,
        track=TrackOutcome(outcomes, clock=lambda: NOW, id_factory=lambda: "o-x"),
        clock=lambda: NOW,
    )
    recorded = await tracker.run_once()

    # al-1: окно 1h наступило → снимок; al-2: ещё рано.
    assert recorded == 1
    outcome = await outcomes.get_by_alert("al-1")
    assert outcome is not None
    assert outcome.price_after_1h == TONAmount.from_ton(D("125"))
    assert await outcomes.get_by_alert("al-2") is None


async def test_outcome_tracker_idempotent() -> None:
    alerts = InMemoryAlertRepository()
    outcomes = InMemoryOutcomeRepository()
    listings = InMemoryListingRepository()
    valuations = InMemoryValuationRepository()

    await listings.save(_listing("125"))
    await valuations.save("getgems:lg-1", _estimate("200"))
    await alerts.save(
        Alert(
            id="al-1",
            user_id="u1",
            listing_id="getgems:lg-1",
            valuation_id="v-1",
            dedup_key="getgems:lg-1",
            sent_at=NOW - timedelta(hours=2),
        )
    )

    ids = iter(("o-1", "o-2"))
    tracker = OutcomeTracker(
        alerts=alerts,
        outcomes=outcomes,
        listings=listings,
        valuations=valuations,
        track=TrackOutcome(outcomes, clock=lambda: NOW, id_factory=lambda: next(ids)),
        clock=lambda: NOW,
    )
    assert await tracker.run_once() == 1
    assert await tracker.run_once() == 0  # окна уже сняты


# ── калибратор ───────────────────────────────────────────────────────────


async def test_calibrator_recommends_threshold_changes() -> None:
    alerts = InMemoryAlertRepository()
    outcomes = InMemoryOutcomeRepository()
    decisions = InMemoryDecisionRepository()
    analytics = AlertAnalytics(alerts, outcomes, decisions)

    # 6 исходов с дискаунтами; precision при пороге 0.30 = 0.8 → рекомендация.
    good, bad = "220", "150"
    for i, (discount, price_24h) in enumerate(
        (
            ("0.50", good),
            ("0.45", good),
            ("0.40", good),
            ("0.35", bad),
            ("0.30", good),
            ("0.25", bad),
        ),
        start=1,
    ):
        await outcomes.save(
            Outcome(
                id=f"o-{i}",
                alert_id=f"al-{i}",
                user_id="u1",
                listing_id=f"lg-{i}",
                alert_price=TONAmount.from_ton(D("120")),
                fair_price=TONAmount.from_ton(D("200")),
                discount=D(discount),
                price_after_24h=TONAmount.from_ton(D(price_24h)),
                computed_at=NOW,
            )
        )

    subscriber = Subscriber(
        user_id="u1",
        policy=AlertPolicy(
            min_discount=D("0.25"),
            min_confidence=D("0.5"),
            price_min=TONAmount.from_ton(D("1")),
            price_max=TONAmount.from_ton(D("1000")),
            min_liquidity=D("0.2"),
            max_risk=D("0.7"),
        ),
        language="ru",
    )
    recommendations = await run_calibrator_once(
        subscribers=FakeSubscriberDirectory([subscriber]),
        analytics=analytics,
        target_precision=D("0.8"),
    )
    assert len(recommendations) == 1
    rec = recommendations[0]
    assert rec.user_id == "u1"
    assert rec.current == D("0.25")
    assert rec.recommended == D("0.30")


async def test_calibrator_keeps_threshold_when_no_change() -> None:
    alerts = InMemoryAlertRepository()
    outcomes = InMemoryOutcomeRepository()
    decisions = InMemoryDecisionRepository()
    analytics = AlertAnalytics(alerts, outcomes, decisions)

    subscriber = Subscriber(
        user_id="u1",
        policy=AlertPolicy(
            min_discount=D("0.25"),
            min_confidence=D("0.5"),
            price_min=TONAmount.from_ton(D("1")),
            price_max=TONAmount.from_ton(D("1000")),
            min_liquidity=D("0.2"),
            max_risk=D("0.7"),
        ),
        language="ru",
    )
    recommendations = await run_calibrator_once(
        subscribers=FakeSubscriberDirectory([subscriber]), analytics=analytics
    )
    assert recommendations == ()  # нет данных → порог не меняется
