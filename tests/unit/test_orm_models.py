"""ORM-модели и конвертеры домен ↔ БД, без подключения к Postgres.

Проверяет: метадата содержит все таблицы ТЗ §5 и конвертеры round-trip
без потерь (деньги nanoTON, Decimal через строки в JSON, адреса raw_str).
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from nftsniper.contexts.alerts.domain.alert import Alert
from nftsniper.contexts.alerts.domain.outcome import Outcome
from nftsniper.contexts.sources.domain.collection import Collection
from nftsniper.contexts.sources.domain.item import Item, Trait, TraitSet
from nftsniper.contexts.sources.domain.listing import Listing
from nftsniper.contexts.sources.domain.marketplace import Marketplace
from nftsniper.contexts.sources.domain.sale import SaleEvent
from nftsniper.contexts.valuation.domain.fair_price import (
    CollectionFeatures,
    EstimationMethod,
    FairPriceEstimate,
)
from nftsniper.infrastructure.database.engine import Base
from nftsniper.infrastructure.database.repositories import (
    _alert_from_model,
    _alert_to_model,
    _collection_from_model,
    _collection_to_model,
    _decimals_from_json,
    _decimals_to_json,
    _estimate_from_model,
    _estimate_to_model,
    _features_from_model,
    _features_to_model,
    _item_from_model,
    _item_to_model,
    _listing_from_model,
    _listing_to_model,
    _outcome_from_model,
    _outcome_to_model,
    _quiet_hours_from_json,
    _quiet_hours_to_json,
    _sale_from_model,
    _sale_to_model,
    _traits_from_json,
    _traits_to_json,
)
from nftsniper.shared.money import TONAmount
from nftsniper.shared.ton_address import TonAddress

D = Decimal
NOW = datetime(2026, 8, 31, 12, 0, 0, tzinfo=UTC)
A = TonAddress(workchain=0, raw_bytes=bytes([0xA1]) * 32)
B = TonAddress(workchain=0, raw_bytes=bytes([0xB2]) * 32)
COLL = "EQChoaGhoaGhoaGhoaGhoaGhoaGhoaGhoaGhoaGhoaGhodWi"

EXPECTED_TABLES = {
    "collections",
    "items",
    "listings",
    "sales",
    "price_stats",
    "valuations",
    "alerts",
    "decisions",
    "outcomes",
    "user_settings",
    "watchlist",
    "alert_registry",
}


def test_metadata_has_all_tables() -> None:
    assert set(Base.metadata.tables) >= EXPECTED_TABLES


def _item() -> Item:
    return Item(
        id="EQItem1",
        collection_id=COLL,
        index=7,
        name="#7",
        traits=TraitSet(traits=(Trait(name="pattern", value="AABB", rarity=D("0.03")),)),
        rarity_rank=D("0.05"),
        rarity_score=D("0.9"),
        media_url="https://ipfs.io/img.png",
    )


def test_item_roundtrip() -> None:
    item = _item()
    assert _item_from_model(_item_to_model(item)) == item


def test_traits_decimal_roundtrip() -> None:
    traits = TraitSet(
        traits=(
            Trait(name="a", value="b", rarity=D("0.123456789")),
            Trait(name="c", value="d", rarity=None),
        )
    )
    assert _traits_from_json(_traits_to_json(traits)) == traits


def test_listing_roundtrip() -> None:
    listing = Listing(
        id="getgems:lg-1",
        external_id="lg-1",
        marketplace=Marketplace.GETGEMS,
        item=_item(),
        price=TONAmount.from_ton(D("120.5")),
        seller=A,
        currency="ton",
        listed_at=NOW,
        raw={"sale": {"endsAt": None}},
    )
    model = _listing_to_model(listing)
    assert model.price_nano == 120_500_000_000
    assert model.seller == A.raw_str
    restored = _listing_from_model(model, _item())
    assert restored == listing


def test_sale_roundtrip() -> None:
    sale = SaleEvent(
        id="tx-1",
        item_id="EQItem1",
        collection_id=COLL,
        price=TONAmount.from_ton(D("99")),
        buyer=B,
        seller=A,
        tx_hash="tx-1",
        sold_at=NOW,
        marketplace=Marketplace.GETGEMS,
        is_suspicious=True,
    )
    assert _sale_from_model(_sale_to_model(sale)) == sale


def test_collection_roundtrip() -> None:
    collection = Collection(
        id=COLL,
        name="Fluffy Punks",
        slug="fluffy-punks",
        marketplace=Marketplace.GETGEMS,
        verified=True,
        created_at=NOW,
        items_count=1000,
        royalty_bps=500,
        risk_score=D("0.25"),
    )
    assert _collection_from_model(_collection_to_model(collection)) == collection


def test_features_roundtrip() -> None:
    features = CollectionFeatures(
        collection_id=COLL,
        floor_p5=TONAmount.from_ton(D("100")),
        median_7d=TONAmount.from_ton(D("120")),
        volume_24h=TONAmount.from_ton(D("0")),
        sales_per_day=D("2.5"),
        sales_7d=18,
        listings_count=20,
        floor_24h_change=D("-0.03"),
        floor_7d_change=D("0.1"),
        as_of=NOW,
        floor_history=(D("90.5"), D("100")),
    )
    assert _features_from_model(_features_to_model(features)) == features


def test_estimate_roundtrip() -> None:
    estimate = FairPriceEstimate(
        value=TONAmount.from_ton(D("207")),
        confidence=D("0.78"),
        method=EstimationMethod.ENSEMBLE,
        lower_bound=TONAmount.from_ton(D("190")),
        upper_bound=TONAmount.from_ton(D("220")),
        sample_size=18,
        explanation=("ансамбль 3 моделей", "интервал 190–220"),
        model_version="7.0.0",
    )
    model = _estimate_to_model("lg-1", estimate)
    assert model.listing_id == "lg-1"
    assert _estimate_from_model(model) == estimate


def test_alert_roundtrip() -> None:
    alert = Alert(
        id="al-1",
        user_id="u1",
        listing_id="lg-1",
        valuation_id="v-1",
        dedup_key="getgems:lg-1",
        sent_at=NOW,
        message_id="tg-42",
    )
    assert _alert_from_model(_alert_to_model(alert)) == alert


def test_outcome_roundtrip() -> None:
    outcome = Outcome(
        id="o-1",
        alert_id="al-1",
        user_id="u1",
        listing_id="lg-1",
        alert_price=TONAmount.from_ton(D("120")),
        fair_price=TONAmount.from_ton(D("207")),
        discount=D("0.42"),
        price_after_1h=TONAmount.from_ton(D("125")),
        price_after_24h=TONAmount.from_ton(D("180")),
        price_after_7d=None,
        sold_at=None,
        sold_price=None,
        computed_at=NOW,
    )
    assert _outcome_from_model(_outcome_to_model(outcome)) == outcome


def test_decimals_json_roundtrip() -> None:
    values = (D("1.5"), D("0.000000001"), D("-0.03"))
    assert _decimals_from_json(_decimals_to_json(values)) == values


def test_quiet_hours_json_roundtrip() -> None:
    hours = ((0, 8), (22, 6))
    assert _quiet_hours_from_json(_quiet_hours_to_json(hours)) == hours
