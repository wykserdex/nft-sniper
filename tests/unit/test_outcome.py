"""Outcome: домен исхода + use case TrackOutcome."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from nftsniper.contexts.alerts.application.outcome_tracking import TrackOutcome
from nftsniper.contexts.alerts.domain.alert import Alert
from nftsniper.contexts.alerts.domain.outcome import Outcome, OutcomeWindow
from nftsniper.contexts.sources.domain.item import Item
from nftsniper.contexts.sources.domain.listing import Listing
from nftsniper.contexts.sources.domain.marketplace import Marketplace
from nftsniper.shared.money import TONAmount
from nftsniper.shared.ton_address import TonAddress
from tests.fakes import InMemoryOutcomeRepository

D = Decimal
NOW = datetime(2026, 8, 31, 12, 0, 0, tzinfo=UTC)
COLL = "EQChoaGhoaGhoaGhoaGhoaGhoaGhoaGhoaGhoaGhoaGhodWi"
SELLER = TonAddress(workchain=0, raw_bytes=bytes([0xD1]) * 32)


def _outcome(**overrides: object) -> Outcome:
    params: dict[str, object] = {
        "id": "o-1",
        "alert_id": "al-1",
        "user_id": "u1",
        "listing_id": "lg-1",
        "alert_price": TONAmount.from_ton(D("120")),
        "fair_price": TONAmount.from_ton(D("200")),
        "discount": D("0.4"),
        "computed_at": NOW,
    }
    params.update(overrides)
    return Outcome(**params)  # type: ignore[arg-type]


# ── снимки ──────────────────────────────────────────────────────────────


def test_apply_snapshot_sets_correct_window() -> None:
    outcome = _outcome()
    after_1h = outcome.apply_snapshot(
        window=OutcomeWindow.ONE_HOUR, price=TONAmount.from_ton(D("130")), at=NOW
    )
    assert after_1h.price_after_1h == TONAmount.from_ton(D("130"))
    assert after_1h.price_after_24h is None

    after_24h = outcome.apply_snapshot(
        window=OutcomeWindow.TWENTY_FOUR_HOURS,
        price=TONAmount.from_ton(D("180")),
        at=NOW,
    )
    assert after_24h.price_after_24h == TONAmount.from_ton(D("180"))

    after_7d = outcome.apply_snapshot(
        window=OutcomeWindow.SEVEN_DAYS, price=TONAmount.from_ton(D("190")), at=NOW
    )
    assert after_7d.price_after_7d == TONAmount.from_ton(D("190"))
    assert after_7d.price_after_24h is None


def test_mark_sold() -> None:
    sold = _outcome().mark_sold(sold_at=NOW, sold_price=TONAmount.from_ton(D("210")), at=NOW)
    assert sold.sold_price == TONAmount.from_ton(D("210"))
    assert sold.sold_at == NOW


# ── оценка ──────────────────────────────────────────────────────────────


def test_final_price_precedence() -> None:
    outcome = _outcome(
        price_after_1h=TONAmount.from_ton(D("130")),
        price_after_24h=TONAmount.from_ton(D("180")),
        price_after_7d=TONAmount.from_ton(D("190")),
        sold_price=TONAmount.from_ton(D("210")),
    )
    assert outcome.final_price() == TONAmount.from_ton(D("210"))  # продажа

    no_sale = _outcome(
        price_after_1h=TONAmount.from_ton(D("130")),
        price_after_7d=TONAmount.from_ton(D("190")),
    )
    assert no_sale.final_price() == TONAmount.from_ton(D("190"))  # 7d

    no_data = _outcome()
    assert no_data.final_price() == TONAmount.from_ton(D("120"))  # цена алерта


def test_confirmed_24h() -> None:
    confirmed = _outcome(price_after_24h=TONAmount.from_ton(D("220")))
    assert confirmed.confirmed_24h() is True

    not_confirmed = _outcome(price_after_24h=TONAmount.from_ton(D("180")))
    assert not_confirmed.confirmed_24h() is False

    sold_ok = _outcome(sold_price=TONAmount.from_ton(D("210")))
    assert sold_ok.confirmed_24h() is True

    no_data = _outcome()
    assert no_data.confirmed_24h() is None

    with_tolerance = _outcome(price_after_24h=TONAmount.from_ton(D("190")))
    assert with_tolerance.confirmed_24h() is False
    assert with_tolerance.confirmed_24h(tolerance=D("0.1")) is True  # цель 180


def test_is_winning() -> None:
    assert _outcome(price_after_24h=TONAmount.from_ton(D("150"))).is_winning() is True
    assert _outcome(price_after_24h=TONAmount.from_ton(D("120"))).is_winning() is False
    assert _outcome(price_after_24h=TONAmount.from_ton(D("100"))).is_winning() is False
    assert _outcome().is_winning() is None


def test_fair_price_must_be_positive() -> None:
    with pytest.raises(ValueError, match="fair_price"):
        _outcome(fair_price=TONAmount.from_ton(D("0")))


# ── TrackOutcome use case ────────────────────────────────────────────────


def _listing(price: str, *, sold: bool = False) -> Listing:
    item = Item(id="EQItem1", collection_id=COLL, index=1, name="#1")
    listing = Listing(
        id="getgems:lg-1",
        external_id="lg-1",
        marketplace=Marketplace.GETGEMS,
        item=item,
        price=TONAmount.from_ton(D(price)),
        seller=SELLER,
        listed_at=NOW,
    )
    if sold:
        listing = listing.mark_sold(at=NOW, price=TONAmount.from_ton(D(price)))
    return listing


def _alert() -> Alert:
    return Alert(
        id="al-1",
        user_id="u1",
        listing_id="lg-1",
        valuation_id="v-1",
        dedup_key="getgems:lg-1",
        sent_at=NOW,
    )


async def test_track_outcome_creates_then_updates() -> None:
    repo = InMemoryOutcomeRepository()
    use_case = TrackOutcome(repo, clock=lambda: NOW, id_factory=lambda: "o-1")

    first = await use_case.run(
        alert=_alert(),
        listing=_listing("125"),
        fair_price=TONAmount.from_ton(D("200")),
        discount=D("0.375"),
        window=OutcomeWindow.ONE_HOUR,
    )
    assert first.id == "o-1"
    assert first.alert_price == TONAmount.from_ton(D("125"))
    assert first.price_after_1h == TONAmount.from_ton(D("125"))

    second = await use_case.run(
        alert=_alert(),
        listing=_listing("150"),
        fair_price=TONAmount.from_ton(D("200")),
        discount=D("0.375"),
        window=OutcomeWindow.TWENTY_FOUR_HOURS,
    )
    assert second.id == "o-1"  # обновление, не дубль
    assert second.price_after_24h == TONAmount.from_ton(D("150"))
    assert second.price_after_1h == TONAmount.from_ton(D("125"))


async def test_track_outcome_marks_sold() -> None:
    repo = InMemoryOutcomeRepository()
    use_case = TrackOutcome(repo, clock=lambda: NOW, id_factory=lambda: "o-1")

    outcome = await use_case.run(
        alert=_alert(),
        listing=_listing("180", sold=True),
        fair_price=TONAmount.from_ton(D("200")),
        discount=D("0.1"),
        window=OutcomeWindow.TWENTY_FOUR_HOURS,
    )
    assert outcome.sold_price == TONAmount.from_ton(D("180"))
    assert outcome.sold_at == NOW
    assert outcome.price_after_24h is None
