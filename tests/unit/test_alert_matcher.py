"""Матчинг листинга с настройками подписчика."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from nftsniper.contexts.alerts.application.matcher import candidate_priority, match_listing
from nftsniper.contexts.alerts.domain.alert import AlertPolicy
from nftsniper.contexts.alerts.domain.candidate import ListingScore, Subscriber
from nftsniper.contexts.sources.domain.item import Item
from nftsniper.contexts.sources.domain.listing import Listing
from nftsniper.contexts.sources.domain.marketplace import Marketplace
from nftsniper.contexts.valuation.domain.discount import Discount
from nftsniper.shared.money import TONAmount
from nftsniper.shared.ton_address import TonAddress

D = Decimal
NOW = datetime(2026, 8, 31, 12, 0, 0, tzinfo=UTC)
COLL = "EQChoaGhoaGhoaGhoaGhoaGhoaGhoaGhoaGhoaGhoaGhodWi"
SELLER = TonAddress(workchain=0, raw_bytes=bytes([0xD1]) * 32)


def _listing(price: str, *, listed_at: datetime | None = None) -> Listing:
    item = Item(id="EQItem1", collection_id=COLL, index=1, name="#1")
    return Listing(
        id="getgems:lg-1",
        external_id="lg-1",
        marketplace=Marketplace.GETGEMS,
        item=item,
        price=TONAmount.from_ton(D(price)),
        seller=SELLER,
        listed_at=listed_at,
    )


def _score(
    price: str = "120",
    *,
    fair: str = "207",
    confidence: str = "0.78",
    liquidity: str = "0.6",
    risk: str = "0.1",
) -> ListingScore:
    listing = _listing(price)
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
    }
    params.update(overrides)
    return AlertPolicy(**params)  # type: ignore[arg-type]


def _subscriber(
    user_id: str = "u1",
    *,
    policy: AlertPolicy | None = None,
    language: str = "ru",
    paused: bool = False,
) -> Subscriber:
    return Subscriber(
        user_id=user_id,
        policy=policy if policy is not None else _policy(),
        language=language,
        paused=paused,
    )


def test_match_allowed_builds_candidate() -> None:
    outcome = match_listing(_score(), _subscriber(), now=NOW, alert_id="al-1")
    assert outcome.allowed
    candidate = outcome.candidate
    assert candidate is not None
    assert candidate.user_id == "u1"
    assert candidate.dedup_key == "getgems:lg-1"
    assert candidate.listing_age_seconds == 0
    assert candidate.priority == candidate_priority(
        discount=candidate.discount, confidence=D("0.78")
    )


def test_match_rejected_by_discount() -> None:
    score = _score(price="190", fair="200")  # discount 0.05 < 0.25
    outcome = match_listing(score, _subscriber(), now=NOW, alert_id="al-1")
    assert not outcome.allowed
    assert outcome.reason == "rejected"
    assert any("discount" in detail for detail in outcome.details)


def test_match_rejected_by_risk() -> None:
    outcome = match_listing(_score(risk="0.9"), _subscriber(), now=NOW, alert_id="al-1")
    assert not outcome.allowed
    assert outcome.reason == "rejected"
    assert any("risk" in detail for detail in outcome.details)


def test_match_paused() -> None:
    outcome = match_listing(_score(), _subscriber(paused=True), now=NOW, alert_id="al-1")
    assert not outcome.allowed
    assert outcome.reason == "paused"


def test_match_quiet() -> None:
    quiet_now = datetime(2026, 8, 31, 3, 0, 0, tzinfo=UTC)
    policy = _policy(quiet_hours=((0, 8),))
    outcome = match_listing(_score(), _subscriber(policy=policy), now=quiet_now, alert_id="al-1")
    assert not outcome.allowed
    assert outcome.reason == "quiet"


def test_listing_age_seconds_from_listed_at() -> None:
    listed_at = NOW - timedelta(seconds=11)
    score = _score()
    score = ListingScore(
        listing=_listing("120", listed_at=listed_at),
        fair_price=score.fair_price,
        confidence=score.confidence,
        discount=score.discount,
        liquidity=score.liquidity,
        risk_value=score.risk_value,
        floor_p5=score.floor_p5,
        median_7d=score.median_7d,
        collection_name=score.collection_name,
    )
    outcome = match_listing(score, _subscriber(), now=NOW, alert_id="al-1")
    assert outcome.candidate is not None
    assert outcome.candidate.listing_age_seconds == 11


def test_candidate_priority_monotonic() -> None:
    base = candidate_priority(discount=D("0.4"), confidence=D("0.5"))
    higher_discount = candidate_priority(discount=D("0.5"), confidence=D("0.5"))
    higher_confidence = candidate_priority(discount=D("0.4"), confidence=D("0.9"))
    assert higher_discount > base
    assert higher_confidence > base
    assert candidate_priority(discount=D("0.5"), confidence=D("0.9")) > higher_discount
