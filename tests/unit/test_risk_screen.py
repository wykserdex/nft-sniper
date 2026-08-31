"""ScreenListing: сборка данных через порты и скоринг."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from nftsniper.contexts.risk.application.screen import ScreenListing, listing_is_auction
from nftsniper.contexts.risk.domain.risk import RiskSeverity
from nftsniper.contexts.sources.domain.chain import WalletInfo
from nftsniper.contexts.sources.domain.collection import Collection
from nftsniper.contexts.sources.domain.item import Item
from nftsniper.contexts.sources.domain.listing import Listing
from nftsniper.contexts.sources.domain.marketplace import Marketplace
from nftsniper.contexts.sources.domain.sale import SaleEvent
from nftsniper.shared.money import TONAmount
from nftsniper.shared.ton_address import TonAddress
from tests.fakes import (
    FakeChainPort,
    FakeCollectionCatalog,
    FakeMediaPort,
    InMemorySaleRepository,
)

D = Decimal
NOW = datetime(2026, 8, 31, 12, 0, 0, tzinfo=UTC)
SELLER = TonAddress(workchain=0, raw_bytes=bytes([0xA1]) * 32)
BUYER = TonAddress(workchain=0, raw_bytes=bytes([0xB2]) * 32)
COLL_ID = "EQChoaGhoaGhoaGhoaGhoaGhoaGhoaGhoaGhoaGhoaGhodWi"


def _collection(name: str = "Fluffy Punks", royalty_bps: int = 0) -> Collection:
    return Collection(
        id=COLL_ID,
        name=name,
        slug=name.lower().replace(" ", "-"),
        marketplace=Marketplace.GETGEMS,
        royalty_bps=royalty_bps,
    )


def _listing(
    name: str = "Fluffy #1", *, media_url: str | None = None, is_auction: bool = False
) -> Listing:
    item = Item(id="EQItem1", collection_id=COLL_ID, index=1, name=name, media_url=media_url)
    raw: dict[str, object] = {
        "sale": {"endsAt": "2026-09-01T00:00:00+00:00" if is_auction else None}
    }
    return Listing(
        id="getgems:lg-1",
        external_id="lg-1",
        marketplace=Marketplace.GETGEMS,
        item=item,
        price=TONAmount.from_ton(D("50")),
        seller=SELLER,
        listed_at=NOW,
        raw=raw,
    )


def _sale(idx: int, price: str, *, item_id: str = "EQItem1") -> SaleEvent:
    return SaleEvent(
        id=f"tx-{idx}",
        item_id=item_id,
        collection_id=COLL_ID,
        price=TONAmount.from_ton(D(price)),
        buyer=BUYER,
        seller=SELLER,
        tx_hash=f"tx-{idx}",
        sold_at=NOW - timedelta(hours=idx),
        marketplace=Marketplace.GETGEMS,
    )


def _build_screen(
    *,
    sales: list[SaleEvent] | None = None,
    wallet: WalletInfo | None = None,
    names: list[str] | None = None,
    media: dict[str, bool] | None = None,
) -> tuple[ScreenListing, InMemorySaleRepository, FakeMediaPort]:
    repo = InMemorySaleRepository()
    for sale in sales or []:
        repo._data[sale.id] = sale
    catalog = FakeCollectionCatalog(names or [])
    media_port = FakeMediaPort(media or {})
    chain = FakeChainPort(wallet=wallet)
    screen = ScreenListing(catalog, media_port, chain, repo)
    return screen, repo, media_port


async def test_screen_clean_listing() -> None:
    screen, _, _ = _build_screen(
        sales=[_sale(i, str(10 + i), item_id=f"EQItem{i}") for i in range(1, 31)],
        wallet=WalletInfo(address=SELLER.raw_str, created_at=NOW - timedelta(days=120)),
        names=["Fluffy Punks", "Telegram Numbers"],
    )
    score = await screen.run(_listing(), collection=_collection())
    assert score.value == D("0")
    assert score.flags == ()


async def test_screen_flags_fresh_seller() -> None:
    screen, _, _ = _build_screen(
        sales=[_sale(i, "10", item_id=f"EQItem{i}") for i in range(10)],
        wallet=WalletInfo(address=SELLER.raw_str, created_at=NOW - timedelta(days=1)),
        names=["Fluffy Punks"],
    )
    score = await screen.run(_listing(), collection=_collection())
    assert score.worst_severity == RiskSeverity.HIGH
    assert "FRESH_SELLER" in {flag.code for flag in score.flags}


async def test_screen_checks_media_when_url_present() -> None:
    screen, _, media_port = _build_screen(
        sales=[_sale(i, "10", item_id=f"EQItem{i}") for i in range(10)],
        wallet=WalletInfo(address=SELLER.raw_str, created_at=NOW - timedelta(days=120)),
        names=["Fluffy Punks"],
        media={"https://ipfs.io/img.png": False},
    )
    score = await screen.run(
        _listing(media_url="https://ipfs.io/img.png"), collection=_collection()
    )
    assert media_port.calls == ["https://ipfs.io/img.png"]
    assert "BROKEN_METADATA" in {flag.code for flag in score.flags}


async def test_screen_skips_media_when_no_url() -> None:
    screen, _, media_port = _build_screen(
        sales=[_sale(i, "10", item_id=f"EQItem{i}") for i in range(10)],
        wallet=WalletInfo(address=SELLER.raw_str, created_at=NOW - timedelta(days=120)),
        names=["Fluffy Punks"],
    )
    score = await screen.run(_listing(media_url=None), collection=_collection())
    assert media_port.calls == []
    assert "BROKEN_METADATA" not in {flag.code for flag in score.flags}


def test_listing_is_auction_reads_raw() -> None:
    assert listing_is_auction(_listing(is_auction=True)) is True
    assert listing_is_auction(_listing(is_auction=False)) is False
    fixed = _listing()
    assert listing_is_auction(fixed) is False
