"""Домен sources: Listing-переходы, dedup, Item/TraitSet, Collection, SaleEvent."""

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from nftsniper.contexts.sources.domain import (
    Collection,
    Item,
    Listing,
    ListingStatus,
    Marketplace,
    SaleEvent,
    Trait,
    TraitSet,
)
from nftsniper.shared.money import TONAmount
from nftsniper.shared.ton_address import TonAddress

T0 = datetime(2026, 8, 31, 12, 0, 0, tzinfo=UTC)
SELLER = TonAddress(workchain=0, raw_bytes=bytes([0x88]) * 32)
BUYER = TonAddress(workchain=0, raw_bytes=bytes([0x42]) * 32)


def make_item(index: int = 888) -> Item:
    return Item(
        id="EQAnon888NftAddress",
        collection_id="EQAnonCollectionAddress",
        index=index,
        name="Anonymous Telegram Number #888",
        traits=TraitSet(
            traits=(
                Trait(name="Number", value="888", rarity=Decimal("0.004")),
                Trait(name="Pattern", value="Repeater"),
            )
        ),
        rarity_rank=Decimal("0.08"),
    )


def make_listing(index: int = 888, price_nano: int = 120_000_000_000) -> Listing:
    return Listing(
        id="lg-1",
        external_id="gg-9001",
        marketplace=Marketplace.GETGEMS,
        item=make_item(index),
        price=TONAmount.from_nano(price_nano),
        seller=SELLER,
        listed_at=T0,
    )


def test_traitset_lookup() -> None:
    item = make_item()
    number = item.traits.get("Number")
    assert number is not None
    assert number.value == "888"
    assert number.rarity == Decimal("0.004")
    assert item.traits.get("Nope") is None
    assert len(item.traits) == 2


def test_listing_dedup_key() -> None:
    assert make_listing().dedup_key == "getgems:gg-9001"


def test_listing_mark_sold() -> None:
    listing = make_listing()
    sold = listing.mark_sold(at=T0, price=TONAmount.from_nano(121_000_000_000))
    assert sold.status is ListingStatus.SOLD
    assert sold.closed_at == T0
    assert sold.price.nano == 121_000_000_000
    assert listing.is_active  # исходный неизменён


def test_listing_sold_keeps_price_if_not_given() -> None:
    listing = make_listing(price_nano=99_000_000_000)
    sold = listing.mark_sold(at=T0)
    assert sold.price == listing.price


def test_listing_transitions_guarded() -> None:
    listing = make_listing().mark_sold(at=T0)
    with pytest.raises(ValueError, match="нельзя продать"):
        listing.mark_sold(at=T0)
    with pytest.raises(ValueError, match="нельзя отменить"):
        listing.mark_cancelled(at=T0)
    with pytest.raises(ValueError, match="нельзя истечь"):
        listing.mark_expired(at=T0)


def test_listing_update_price_only_active() -> None:
    listing = make_listing()
    changed = listing.update_price(price=TONAmount.from_ton(Decimal("118")))
    assert changed.price.formatted == "118"
    with pytest.raises(ValueError, match="нельзя менять цену"):
        listing.mark_sold(at=T0).update_price(price=TONAmount.from_ton(Decimal("1")))


def test_listing_bad_status_rejected() -> None:
    with pytest.raises(ValueError, match="статус"):
        Listing(
            id="x",
            external_id="x",
            marketplace=Marketplace.GETGEMS,
            item=make_item(),
            price=TONAmount.zero(),
            seller=SELLER,
            status="weird",  # type: ignore[arg-type]
        )


def test_sale_event() -> None:
    sale = SaleEvent(
        id="s-1",
        item_id="EQAnon888NftAddress",
        collection_id="EQAnonCollectionAddress",
        price=TONAmount.from_ton(Decimal("214")),
        buyer=BUYER,
        seller=SELLER,
        tx_hash="abc123",
        sold_at=T0,
        marketplace=Marketplace.GETGEMS,
    )
    assert sale.is_suspicious is False
    suspicious = sale
    assert suspicious.price.formatted == "214"


def test_collection_with_risk_score() -> None:
    collection = Collection(id="EQColl", name="Anonymous Numbers", slug="anon-numbers")
    assert collection.risk_score is None
    risky = collection.with_risk_score(Decimal("0.7"))
    assert risky.risk_score == Decimal("0.7")
    assert collection.risk_score is None
