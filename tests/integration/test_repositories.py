"""Интеграционные тесты Postgres-репозиториев.

Запускаются на сервисах CI (docker compose up -d postgres redis). Без базы —
skip, как в test_infra.py. Проверяют round-trip домен ↔ БД и выборки
(дедуп, rate limit, окна продаж, трекинг исходов).
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nftsniper.config.settings import Settings
from nftsniper.contexts.alerts.domain.alert import Alert, Decision
from nftsniper.contexts.alerts.domain.outcome import Outcome
from nftsniper.contexts.sources.domain.collection import Collection
from nftsniper.contexts.sources.domain.item import Item
from nftsniper.contexts.sources.domain.listing import Listing
from nftsniper.contexts.sources.domain.marketplace import Marketplace
from nftsniper.contexts.sources.domain.sale import SaleEvent
from nftsniper.contexts.valuation.domain.fair_price import (
    CollectionFeatures,
    EstimationMethod,
    FairPriceEstimate,
)
from nftsniper.entrypoints.bot.domain import UserSettings
from nftsniper.infrastructure.database.engine import (
    create_database,
    create_session_factory,
    ping_db,
)
from nftsniper.infrastructure.database.repositories import (
    PostgresAlertRepository,
    PostgresCollectionRepository,
    PostgresDecisionRepository,
    PostgresFeatureStore,
    PostgresListingRepository,
    PostgresOutcomeRepository,
    PostgresSaleRepository,
    PostgresUserSettingsStore,
    PostgresValuationRepository,
    PostgresWatchlistStore,
)
from nftsniper.shared.money import TONAmount
from nftsniper.shared.ton_address import TonAddress

D = Decimal
NOW = datetime(2026, 8, 31, 12, 0, 0, tzinfo=UTC)
A = TonAddress(workchain=0, raw_bytes=bytes([0xA1]) * 32)
B = TonAddress(workchain=0, raw_bytes=bytes([0xB2]) * 32)
COLL = "EQChoaGhoaGhoaGhoaGhoaGhoaGhoaGhoaGhoaGhoaGhodWi"


def _settings() -> Settings:
    return Settings(_env_file=None)


async def _probe_db() -> bool:
    engine = create_database(_settings())
    try:
        await ping_db(engine)
    except Exception:
        await engine.dispose()
        return False
    await engine.dispose()
    return True


@pytest.fixture(scope="module", autouse=True)
def _require_db() -> None:
    if not asyncio.run(_probe_db()):
        pytest.skip("Postgres недоступен (docker compose up -d postgres redis)")


@pytest.fixture
async def sessions() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    engine = create_database(_settings())
    command.upgrade(Config("alembic.ini"), "head")
    factory = create_session_factory(engine)
    yield factory
    command.downgrade(Config("alembic.ini"), "base")
    await engine.dispose()


def _item() -> Item:
    return Item(id="EQItem1", collection_id=COLL, index=1, name="#1")


def _listing(price: str = "120") -> Listing:
    return Listing(
        id="getgems:lg-1",
        external_id="lg-1",
        marketplace=Marketplace.GETGEMS,
        item=_item(),
        price=TONAmount.from_ton(D(price)),
        seller=A,
        listed_at=NOW,
    )


def _sale(idx: int, *, hours_ago: int, price: str = "100") -> SaleEvent:
    return SaleEvent(
        id=f"tx-{idx}",
        item_id=f"EQItem{idx:03d}",
        collection_id=COLL,
        price=TONAmount.from_ton(D(price)),
        buyer=B,
        seller=A,
        tx_hash=f"tx-{idx}",
        sold_at=NOW - timedelta(hours=hours_ago),
        marketplace=Marketplace.GETGEMS,
    )


async def test_listing_and_item_roundtrip(sessions: async_sessionmaker[AsyncSession]) -> None:
    repo = PostgresListingRepository(sessions)
    await repo.save(_listing("120"))

    restored = await repo.get("getgems:lg-1")
    assert restored is not None
    assert restored == _listing("120")
    assert restored.item.name == "#1"

    by_key = await repo.get_by_dedup_key("getgems:lg-1")
    assert by_key is not None
    assert by_key.id == "getgems:lg-1"

    active = await repo.list_active(COLL)
    assert len(active) == 1


async def test_sales_window_queries(sessions: async_sessionmaker[AsyncSession]) -> None:
    repo = PostgresSaleRepository(sessions)
    await repo.add(_sale(1, hours_ago=1))
    await repo.add(_sale(2, hours_ago=25))  # за окном

    recent = await repo.list_by_item("EQItem001", NOW - timedelta(hours=24))
    assert [sale.id for sale in recent] == ["tx-1"]

    by_collection = await repo.list_by_collection(COLL, NOW - timedelta(hours=48))
    assert {sale.id for sale in by_collection} == {"tx-1", "tx-2"}


async def test_collection_and_features_roundtrip(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    collections = PostgresCollectionRepository(sessions)
    await collections.save(
        Collection(
            id=COLL,
            name="Fluffy Punks",
            slug="fluffy-punks",
            marketplace=Marketplace.GETGEMS,
            royalty_bps=500,
        )
    )
    restored = await collections.get(COLL)
    assert restored is not None
    assert restored.royalty_bps == 500
    assert await collections.list_names() == ["Fluffy Punks"]

    features = CollectionFeatures(
        collection_id=COLL,
        floor_p5=TONAmount.from_ton(D("100")),
        median_7d=TONAmount.from_ton(D("120")),
        volume_24h=TONAmount.from_ton(D("0")),
        sales_per_day=D("2.5"),
        sales_7d=18,
        listings_count=20,
        floor_24h_change=D("0"),
        floor_7d_change=D("0"),
        as_of=NOW,
        floor_history=(D("90"), D("100")),
    )
    store = PostgresFeatureStore(sessions)
    await store.save(features)
    loaded = await store.load(COLL)
    assert loaded == features


async def test_valuation_roundtrip(sessions: async_sessionmaker[AsyncSession]) -> None:
    repo = PostgresValuationRepository(sessions)
    estimate = FairPriceEstimate(
        value=TONAmount.from_ton(D("207")),
        confidence=D("0.78"),
        method=EstimationMethod.ENSEMBLE,
        lower_bound=TONAmount.from_ton(D("190")),
        upper_bound=TONAmount.from_ton(D("220")),
        sample_size=18,
        explanation=("ансамбль",),
        model_version="7.0.0",
    )
    await repo.save("getgems:lg-1", estimate)
    assert await repo.get_by_listing("getgems:lg-1") == estimate


async def test_alert_dedup_and_rate_limit(sessions: async_sessionmaker[AsyncSession]) -> None:
    repo = PostgresAlertRepository(sessions)
    await repo.save(
        Alert(
            id="al-1",
            user_id="u1",
            listing_id="lg-1",
            valuation_id="v-1",
            dedup_key="getgems:lg-1",
            sent_at=NOW,
        )
    )
    found = await repo.find_recent_by_dedup("u1", "getgems:lg-1", NOW - timedelta(hours=6))
    assert found is not None
    assert found.id == "al-1"
    assert await repo.count_recent("u1", NOW - timedelta(hours=1)) == 1
    assert [alert.id for alert in await repo.list_recent(NOW - timedelta(hours=1))] == ["al-1"]


async def test_decision_and_outcome_roundtrip(sessions: async_sessionmaker[AsyncSession]) -> None:
    decisions = PostgresDecisionRepository(sessions)
    await decisions.save(
        Decision(
            id="d-1", alert_id="al-1", user_id="u1", action="taken", latency_ms=850, created_at=NOW
        )
    )
    assert len(await decisions.list_by_user("u1")) == 1

    outcomes = PostgresOutcomeRepository(sessions)
    outcome = Outcome(
        id="o-1",
        alert_id="al-1",
        user_id="u1",
        listing_id="lg-1",
        alert_price=TONAmount.from_ton(D("120")),
        fair_price=TONAmount.from_ton(D("207")),
        discount=D("0.42"),
        price_after_24h=TONAmount.from_ton(D("180")),
        computed_at=NOW,
    )
    await outcomes.save(outcome)
    restored = await outcomes.get_by_alert("al-1")
    assert restored == outcome


async def test_user_settings_roundtrip(sessions: async_sessionmaker[AsyncSession]) -> None:
    store = PostgresUserSettingsStore(sessions)
    settings = UserSettings(
        user_id="u1",
        language="ru",
        min_discount=D("0.3"),
        min_confidence=D("0.6"),
        price_min=TONAmount.from_ton(D("5")),
        price_max=TONAmount.from_ton(D("500")),
        min_liquidity=D("0.2"),
        max_risk=D("0.6"),
        quiet_hours=((22, 6),),
        muted_collections=("EQabc",),
    )
    await store.save(settings)
    restored = await store.get("u1")
    assert restored is not None
    assert restored.min_discount == D("0.3")
    assert restored.quiet_hours == ((22, 6),)
    assert restored.muted_collections == ("EQabc",)
    assert await store.list_users() == ("u1",)

    watchlist = PostgresWatchlistStore(sessions)
    await watchlist.add("u1", "EQItem1")
    assert await watchlist.list("u1") == ("EQItem1",)
