"""Конвейер листингов: poll → score → risk → notify, end-to-end.

Проверяет полный путь ТЗ §6 на fake'ах без I/O: новый листинг оценивается,
скринится (risk), матчится с подписчиком и доставляется; рискованный
листинг отсекается порогом max_risk подписчика.
"""

from __future__ import annotations

import itertools
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from nftsniper.contexts.alerts.application.engine import AlertEngine
from nftsniper.contexts.alerts.domain.alert import AlertPolicy
from nftsniper.contexts.alerts.domain.candidate import Subscriber
from nftsniper.contexts.risk.application.screen import ScreenListing
from nftsniper.contexts.sources.application.poll_listings import PollListings
from nftsniper.contexts.sources.domain.chain import WalletInfo
from nftsniper.contexts.sources.domain.collection import Collection
from nftsniper.contexts.sources.domain.item import Item
from nftsniper.contexts.sources.domain.listing import Listing
from nftsniper.contexts.sources.domain.marketplace import Marketplace
from nftsniper.contexts.sources.domain.sale import SaleEvent
from nftsniper.contexts.valuation.adapters.ensemble import EnsemblePriceModel
from nftsniper.contexts.valuation.application.estimate_fair_price import (
    EstimateFairPrice,
    ScoreListing,
)
from nftsniper.contexts.valuation.application.rebuild_stats import RebuildStats
from nftsniper.contexts.valuation.domain.fair_price import CollectionFeatures
from nftsniper.entrypoints.bot.render import render_candidate
from nftsniper.entrypoints.workers.pipeline import ListingPipeline, getgems_item_url
from nftsniper.shared.money import TONAmount
from nftsniper.shared.ton_address import TonAddress
from tests.fakes import (
    FakeChainPort,
    FakeCollectionCatalog,
    FakeMarketplacePort,
    FakeMediaPort,
    FakeNotifier,
    FakeSubscriberDirectory,
    InMemoryAlertRepository,
    InMemoryFeatureStore,
    InMemoryListingRepository,
    InMemorySaleRepository,
    InMemoryValuationRepository,
)

D = Decimal
NOW = datetime(2026, 8, 31, 12, 0, 0, tzinfo=UTC)
COLL = "EQChoaGhoaGhoaGhoaGhoaGhoaGhoaGhoaGhoaGhoaGhodWi"
SELLER = TonAddress(workchain=0, raw_bytes=bytes([0xD1]) * 32)
BUYER = TonAddress(workchain=0, raw_bytes=bytes([0xE1]) * 32)


def _collection() -> Collection:
    return Collection(
        id=COLL,
        name="Fluffy Punks",
        slug="fluffy-punks",
        marketplace=Marketplace.GETGEMS,
        royalty_bps=0,
    )


def _listing(price: str = "70") -> Listing:
    item = Item(id="EQItem1", collection_id=COLL, index=1, name="Fluffy #1")
    return Listing(
        id="getgems:lg-1",
        external_id="lg-1",
        marketplace=Marketplace.GETGEMS,
        item=item,
        price=TONAmount.from_ton(D(price)),
        seller=SELLER,
        listed_at=NOW,
    )


def _sales(count: int, price: str = "100") -> list[SaleEvent]:
    return [
        SaleEvent(
            id=f"tx-{i}",
            item_id=f"EQItem{i:03d}",
            collection_id=COLL,
            price=TONAmount.from_ton(D(price)),
            buyer=BUYER,
            seller=SELLER,
            tx_hash=f"tx-{i}",
            sold_at=NOW - timedelta(days=1, hours=i),
            marketplace=Marketplace.GETGEMS,
        )
        for i in range(count)
    ]


def _active_listings(count: int = 20, price: str = "100") -> list[Listing]:
    listings: list[Listing] = []
    for i in range(count):
        item = Item(id=f"EQItem{i:03d}", collection_id=COLL, index=i, name=f"#{i}")
        listings.append(
            Listing(
                id=f"getgems:act-{i}",
                external_id=f"act-{i}",
                marketplace=Marketplace.GETGEMS,
                item=item,
                price=TONAmount.from_ton(D(price)),
                seller=SELLER,
                listed_at=NOW - timedelta(days=1),
            )
        )
    return listings


def _features(*, sales_per_day: str = "2", sales_7d: int = 10) -> CollectionFeatures:
    return CollectionFeatures(
        collection_id=COLL,
        floor_p5=TONAmount.from_ton(D("100")),
        median_7d=TONAmount.from_ton(D("120")),
        volume_24h=TONAmount.from_ton(D("0")),
        sales_per_day=D(sales_per_day),
        listings_count=20,
        floor_24h_change=D("0"),
        floor_7d_change=D("0"),
        as_of=NOW,
        sales_7d=sales_7d,
    )


def _subscriber(*, max_risk: str = "0.7", min_discount: str = "0.25") -> Subscriber:
    return Subscriber(
        user_id="u1",
        policy=AlertPolicy(
            min_discount=D(min_discount),
            min_confidence=D("0.1"),
            price_min=TONAmount.from_ton(D("1")),
            price_max=TONAmount.from_ton(D("1000")),
            min_liquidity=D("0.2"),
            max_risk=D(max_risk),
        ),
        language="ru",
    )


def _build(
    *,
    seed_features: bool = True,
    sales: list[SaleEvent] | None = None,
    wallet_age_days: int = 120,
) -> tuple[ListingPipeline, FakeNotifier, InMemoryFeatureStore]:
    listings_repo = InMemoryListingRepository()
    for listing in _active_listings():
        listings_repo._data[listing.id] = listing

    sales_repo = InMemorySaleRepository()
    for sale in sales or _sales(10):
        sales_repo._data[sale.id] = sale

    features = InMemoryFeatureStore()
    if seed_features:
        features._data[COLL] = _features()

    marketplace = FakeMarketplacePort(
        collections=[_collection()],
        listings=[_listing()],
    )

    poller = PollListings(marketplace, listings_repo, clock=lambda: NOW)
    rebuild = RebuildStats(listings_repo, sales_repo, features, clock=lambda: NOW)
    valuations = InMemoryValuationRepository()
    scorer = ScoreListing(
        EstimateFairPrice(EnsemblePriceModel(), features, valuations),
        clock=lambda: NOW,
    )
    screen = ScreenListing(
        FakeCollectionCatalog(["Fluffy Punks"]),
        FakeMediaPort(),
        FakeChainPort(
            wallet=WalletInfo(
                address=SELLER.raw_str, created_at=NOW - timedelta(days=wallet_age_days)
            )
        ),
        sales_repo,
        clock=lambda: NOW,
    )

    notifier = FakeNotifier()
    alerts = InMemoryAlertRepository()
    counter = itertools.count(1)
    engine = AlertEngine(
        notifier=notifier,
        alerts=alerts,
        subscribers=FakeSubscriberDirectory([_subscriber()]),
        renderer=render_candidate,
        clock=lambda: NOW,
        id_factory=lambda: f"al-{next(counter)}",
    )

    pipeline = ListingPipeline(
        poller=poller,
        features=features,
        rebuild=rebuild,
        scorer=scorer,
        screen=screen,
        collections=marketplace,
        engine=engine,
    )
    return pipeline, notifier, features


async def test_pipeline_clean_deal_delivered() -> None:
    pipeline, notifier, _ = _build()
    report = await pipeline.run(COLL)

    assert report.discovered == 1
    assert report.scored == 1
    assert report.risk_flagged == 0
    assert report.delivered == 1
    assert report.dropped == 0

    assert len(notifier.sent) == 1
    user_id, message = notifier.sent[0]
    assert user_id == "u1"
    assert "Fluffy #1" in message.text
    # кнопка-ссылка на GetGems с диплинком предмета
    assert any(button.url == getgems_item_url("EQItem1") for button in message.buttons)


async def test_pipeline_risk_blocks_delivery() -> None:
    # Свежий продавец → FRESH_SELLER (risk 0.9) > max_risk 0.7 → алерт не уходит.
    pipeline, notifier, _ = _build(wallet_age_days=1)
    report = await pipeline.run(COLL)

    assert report.scored == 1
    assert report.risk_flagged == 1
    assert report.matched == 0  # риск выше порога → matcher отвергает (rejected)
    assert report.delivered == 0
    assert report.dropped == 1
    assert notifier.sent == []


async def test_pipeline_rebuilds_features_when_missing() -> None:
    pipeline, _, features = _build(seed_features=False)
    assert await features.load(COLL) is None  # фич нет

    report = await pipeline.run(COLL)

    assert report.scored == 1
    assert await features.load(COLL) is not None  # RebuildStats заполнил
    assert report.delivered == 1


async def test_pipeline_no_new_listings() -> None:
    pipeline, notifier, _ = _build()
    report = await pipeline.run("EQUnknownCollection")
    assert report.discovered == 0
    assert report.scored == 0
    assert notifier.sent == []


def test_getgems_item_url() -> None:
    assert getgems_item_url("EQItem1") == "https://getgems.io/nft/EQItem1"
