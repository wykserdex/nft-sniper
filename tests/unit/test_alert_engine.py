"""AlertEngine: дедуп, rate limit, quiet hours, приоритизация.

Acceptance ТЗ §7: нет дублей, лимиты соблюдаются, при всплеске 1000
листингов/мин очередь не деградирует (отправляется не больше бюджета).
"""

from __future__ import annotations

import itertools
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from nftsniper.contexts.alerts.application.engine import (
    AlertEngine,
    PrioritizedQueue,
    Renderer,
)
from nftsniper.contexts.alerts.domain.alert import Alert, AlertMessage, AlertPolicy
from nftsniper.contexts.alerts.domain.candidate import (
    AlertCandidate,
    ListingScore,
    Subscriber,
)
from nftsniper.contexts.sources.domain.item import Item
from nftsniper.contexts.sources.domain.listing import Listing
from nftsniper.contexts.sources.domain.marketplace import Marketplace
from nftsniper.contexts.valuation.domain.discount import Discount
from nftsniper.entrypoints.bot.render import render_candidate
from nftsniper.shared.money import TONAmount
from nftsniper.shared.ton_address import TonAddress
from tests.fakes import (
    FakeNotifier,
    FakeSubscriberDirectory,
    InMemoryAlertRepository,
)

D = Decimal
NOW = datetime(2026, 8, 31, 12, 0, 0, tzinfo=UTC)
COLL = "EQChoaGhoaGhoaGhoaGhoaGhoaGhoaGhoaGhodWi"
SELLER = TonAddress(workchain=0, raw_bytes=bytes([0xD1]) * 32)


def _listing(index: int, price: str, *, external_id: str | None = None) -> Listing:
    item = Item(id=f"EQItem{index}", collection_id=COLL, index=index, name=f"#{index}")
    ext = external_id if external_id is not None else f"lg-{index}"
    return Listing(
        id=f"getgems:{ext}",
        external_id=ext,
        marketplace=Marketplace.GETGEMS,
        item=item,
        price=TONAmount.from_ton(D(price)),
        seller=SELLER,
        listed_at=NOW,
    )


def _score(
    index: int,
    price: str = "120",
    *,
    fair: str = "207",
    confidence: str = "0.78",
    liquidity: str = "0.6",
    risk: str = "0.1",
    external_id: str | None = None,
) -> ListingScore:
    listing = _listing(index, price, external_id=external_id)
    return ListingScore(
        listing=listing,
        fair_price=TONAmount.from_ton(D(fair)),
        confidence=D(confidence),
        discount=Discount.calculate(TONAmount.from_ton(D(fair)), listing.price),
        liquidity=D(liquidity),
        risk_value=D(risk),
        floor_p5=TONAmount.from_ton(D("195")),
        median_7d=TONAmount.from_ton(D("214")),
        sales_7d=18,
        floor_24h_change=D("-0.03"),
        collection_name="Anonymous Numbers",
    )


def _policy(**overrides: object) -> AlertPolicy:
    params: dict[str, object] = {
        "min_discount": D("0.25"),
        "min_confidence": D("0.5"),
        "price_min": TONAmount.from_ton(D("1")),
        "price_max": TONAmount.from_ton(D("1000")),
        "min_liquidity": D("0.2"),
        "max_risk": D("0.7"),
        "max_alerts_per_hour": 20,
    }
    params.update(overrides)
    return AlertPolicy(**params)  # type: ignore[arg-type]


def _engine(
    *subscribers: Subscriber,
    notifier: FakeNotifier | None = None,
    alerts: InMemoryAlertRepository | None = None,
    renderer: Renderer | None = None,
) -> tuple[AlertEngine, FakeNotifier, InMemoryAlertRepository]:
    nf = notifier if notifier is not None else FakeNotifier()
    repo = alerts if alerts is not None else InMemoryAlertRepository()
    counter = itertools.count(1)
    engine = AlertEngine(
        notifier=nf,
        alerts=repo,
        subscribers=FakeSubscriberDirectory(subscribers),
        renderer=renderer if renderer is not None else render_candidate,
        clock=lambda: NOW,
        id_factory=lambda: f"al-{next(counter)}",
    )
    return engine, nf, repo


def _subscriber(
    user_id: str = "u1", *, policy: AlertPolicy | None = None, paused: bool = False
) -> Subscriber:
    return Subscriber(
        user_id=user_id,
        policy=policy if policy is not None else _policy(),
        language="ru",
        paused=paused,
    )


# ── доставка ────────────────────────────────────────────────────────────


async def test_deliver_sends_and_saves() -> None:
    engine, notifier, repo = _engine(_subscriber())
    report = await engine.deliver(_score(1))
    assert report.matched == 1
    assert report.sent == 1
    assert len(notifier.sent) == 1
    user_id, message = notifier.sent[0]
    assert user_id == "u1"
    assert "42%" in message.text
    alert = next(iter(repo._data.values()))
    assert alert.user_id == "u1"
    assert alert.dedup_key == "getgems:lg-1"
    assert alert.message_id == "tg-1"


async def test_deliver_rejects_below_threshold() -> None:
    engine, notifier, _ = _engine(_subscriber())
    report = await engine.deliver(_score(1, price="190", fair="200"))
    assert report.sent == 0
    assert report.rejected == 1
    assert notifier.sent == []


async def test_deliver_dedups_same_listing() -> None:
    engine, notifier, repo = _engine(_subscriber())
    same = _score(1, external_id="shared")
    other = _score(2, external_id="shared")  # тот же dedup_key
    report = await engine.deliver_batch((same, other))
    assert report.matched == 2
    assert report.sent == 1
    assert report.deduped == 1
    assert len(notifier.sent) == 1
    assert len(repo._data) == 1


async def test_deliver_rate_limited() -> None:
    engine, notifier, repo = _engine(_subscriber(policy=_policy(max_alerts_per_hour=2)))
    scores = tuple(_score(i) for i in range(1, 6))
    report = await engine.deliver_batch(scores)
    assert report.matched == 5
    assert report.sent == 2
    assert report.rate_limited == 3
    assert len(notifier.sent) == 2
    assert await repo.count_recent("u1", NOW - timedelta(hours=1)) == 2


async def test_deliver_quiet_hours() -> None:
    engine, notifier, _ = _engine(_subscriber(policy=_policy(quiet_hours=((0, 16),))))
    report = await engine.deliver(_score(1))
    assert report.sent == 0
    assert report.quiet == 1
    assert notifier.sent == []


async def test_deliver_paused() -> None:
    engine, notifier, _ = _engine(_subscriber(paused=True))
    report = await engine.deliver(_score(1))
    assert report.sent == 0
    assert report.paused == 1
    assert notifier.sent == []


async def test_deliver_respects_prior_sends() -> None:
    repo = InMemoryAlertRepository()
    for i in range(2):
        await repo.save(
            Alert(
                id=f"old-{i}",
                user_id="u1",
                listing_id=f"lg-{i}",
                valuation_id="",
                dedup_key=f"getgems:old-{i}",
                sent_at=NOW,
            )
        )
    engine, notifier, _ = _engine(_subscriber(policy=_policy(max_alerts_per_hour=3)), alerts=repo)
    report = await engine.deliver_batch(tuple(_score(i) for i in range(1, 6)))
    assert report.sent == 1  # бюджет 3 - 2 уже отправленных
    assert report.rate_limited == 4
    assert len(notifier.sent) == 1


# ── приоритизация и всплеск ─────────────────────────────────────────────


async def test_deliver_sends_best_deals_first() -> None:
    received: list[str] = []

    def recording_renderer(candidate: AlertCandidate) -> AlertMessage:
        received.append(candidate.discount.quantize(D("0.01")).to_eng_string())
        return render_candidate(candidate)

    engine, _, _ = _engine(
        _subscriber(policy=_policy(max_alerts_per_hour=10)),
        renderer=recording_renderer,
    )
    scores = (
        _score(1, price="120", fair="207"),  # ~42%
        _score(2, price="100", fair="200"),  # 50%
        _score(3, price="140", fair="200"),  # 30%
    )
    report = await engine.deliver_batch(scores)
    assert report.sent == 3
    assert received == ["0.50", "0.42", "0.30"]  # лучшие сделки первыми


async def test_deliver_burst_stays_bounded() -> None:
    """Всплеск 1000 листингов: отправляется не больше бюджета (ТЗ §7)."""
    engine, notifier, repo = _engine(_subscriber(policy=_policy(max_alerts_per_hour=20)))
    scores = tuple(_score(i) for i in range(1, 1001))
    report = await engine.deliver_batch(scores)
    assert report.matched == 1000
    assert report.sent == 20
    assert report.rate_limited == 980
    assert len(notifier.sent) == 20
    assert len(report.alerts) == 20
    assert len(repo._data) == 20


def test_prioritized_queue_best_first() -> None:
    queue = PrioritizedQueue()
    queue.push(D("0.3"), "c")
    queue.push(D("0.5"), "a")
    queue.push(D("0.4"), "b")
    assert queue.pop() == "a"
    assert queue.pop() == "b"
    assert queue.pop() == "c"
    assert queue.pop() is None
