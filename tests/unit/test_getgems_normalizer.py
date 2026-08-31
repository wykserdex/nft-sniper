"""Нормализация GetGems: сырые узлы → доменные модели (защитное чтение)."""

from nftsniper.contexts.sources.adapters.getgems.normalizer import (
    parse_collection,
    parse_item,
    parse_listing,
    parse_sale,
    slugify,
)
from nftsniper.contexts.sources.domain.marketplace import Marketplace

COLL = "EQChoaGhoaGhoaGhoaGhoaGhoaGhoaGhoaGhoaGhoaGhodWi"
ITEM = "EQDBwcHBwcHBwcHBwcHBwcHBwcHBwcHBwcHBwcHBwcHBwS2C"
SELLER = "EQDR0dHR0dHR0dHR0dHR0dHR0dHR0dHR0dHR0dHR0dHR0QZy"
BUYER = "EQDh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4Xpi"


def _item_node(**overrides: object) -> dict[str, object]:
    node: dict[str, object] = {
        "address": ITEM,
        "index": 888,
        "name": "Anonymous Telegram Number #888",
        "collectionAddress": COLL,
        "ownerAddress": SELLER,
        "attributes": [
            {"traitType": "Number", "value": "888"},
            {"traitType": "Pattern", "value": "Repeater"},
        ],
    }
    node.update(overrides)
    return node


def test_parse_collection() -> None:
    collection = parse_collection(
        {
            "address": COLL,
            "nextItemIndex": 10000,
            "verified": True,
            "meta": {"name": "Anonymous Telegram Numbers"},
        }
    )
    assert collection is not None
    assert collection.id == COLL
    assert collection.name == "Anonymous Telegram Numbers"
    assert collection.slug == "anonymous-telegram-numbers"
    assert collection.marketplace is Marketplace.GETGEMS
    assert collection.verified is True
    assert collection.items_count == 10000


def test_parse_collection_missing_address_is_none() -> None:
    assert parse_collection({"meta": {"name": "X"}}) is None


def test_parse_collection_name_fallback() -> None:
    collection = parse_collection({"address": COLL, "nextItemIndex": 5})
    assert collection is not None
    assert collection.name.startswith("Collection ")


def test_parse_item_traits_and_name() -> None:
    item = parse_item(_item_node())
    assert item is not None
    assert item.id == ITEM
    assert item.collection_id == COLL
    assert item.index == 888
    assert item.name == "Anonymous Telegram Number #888"
    assert len(item.traits) == 2
    number = item.traits.get("Number")
    assert number is not None
    assert number.value == "888"
    assert number.rarity is None


def test_parse_item_name_fallback_to_index() -> None:
    item = parse_item(_item_node(name=None))
    assert item is not None
    assert item.name == "#888"


def test_parse_listing_simple_sale() -> None:
    listing = parse_listing(
        _item_node(),
        {
            "__typename": "NftSaleSimple",
            "address": "EQDx8fHx8fHx8fHx8fHx8fHx8fHx8fHx8fHx8fHx8fHx8VGS",
            "fullPrice": "120000000000",
            "createdAt": "2026-08-31T16:40:00+00:00",
            "owner": SELLER,
        },
    )
    assert listing is not None
    assert listing.dedup_key == "getgems:EQDx8fHx8fHx8fHx8fHx8fHx8fHx8fHx8fHx8fHx8fHx8VGS"
    assert listing.price.formatted == "120"
    assert listing.seller.user_friendly(bounceable=True) == SELLER
    assert listing.listed_at is not None
    assert listing.raw is not None
    assert "sale" in listing.raw


def test_parse_listing_auction_uses_max_bid() -> None:
    listing = parse_listing(
        _item_node(),
        {
            "__typename": "NftSaleAuction",
            "address": "EQDz8_Pz8_Pz8_Pz8_Pz8_Pz8_Pz8_Pz8_Pz8_Pz8_Pz81Ts",
            "minBid": "140000000000",
            "maxBid": "150000000000",
            "createdAt": "2026-08-31T16:38:00+00:00",
            "owner": SELLER,
        },
    )
    assert listing is not None
    assert listing.price.formatted == "150"


def test_parse_listing_unpriced_is_none() -> None:
    assert parse_listing(_item_node(), {"address": "x", "owner": SELLER}) is None


def test_parse_listing_seller_fallback_to_owner_address() -> None:
    listing = parse_listing(
        _item_node(),
        {
            "address": "EQDz8_Pz8_Pz8_Pz8_Pz8_Pz8_Pz8_Pz8_Pz8_Pz8_Pz81Ts",
            "fullPrice": "120000000000",
        },
    )
    assert listing is not None
    assert listing.seller.user_friendly(bounceable=True) == SELLER


def test_parse_sale() -> None:
    sale = parse_sale(
        {
            "txHash": "tx-abc",
            "timestamp": "2026-08-31T10:00:00+00:00",
            "price": "214000000000",
            "buyer": BUYER,
            "seller": SELLER,
            "nft": {"address": ITEM, "collectionAddress": COLL},
        }
    )
    assert sale is not None
    assert sale.id == "tx-abc"
    assert sale.price.formatted == "214"
    assert sale.item_id == ITEM
    assert sale.collection_id == COLL
    assert sale.marketplace is Marketplace.GETGEMS
    assert sale.is_suspicious is False


def test_parse_sale_collection_from_argument() -> None:
    sale = parse_sale(
        {
            "txHash": "tx-x",
            "timestamp": "2026-08-31T10:00:00+00:00",
            "price": "1",
            "buyer": BUYER,
            "seller": SELLER,
            "nft": {"address": ITEM},
        },
        collection_address=COLL,
    )
    assert sale is not None
    assert sale.collection_id == COLL


def test_parse_sale_missing_tx_is_none() -> None:
    assert parse_sale({"timestamp": "2026-08-31T10:00:00+00:00", "price": "1"}) is None


def test_parse_sale_bad_price_is_none() -> None:
    assert (
        parse_sale(
            {
                "txHash": "tx-x",
                "timestamp": "2026-08-31T10:00:00+00:00",
                "price": "не число",
                "buyer": BUYER,
                "seller": SELLER,
                "nft": {"address": ITEM},
            }
        )
        is None
    )


def test_parse_sale_bad_timestamp_is_none() -> None:
    assert (
        parse_sale(
            {
                "txHash": "tx-x",
                "timestamp": "вчера",
                "price": "1",
                "buyer": BUYER,
                "seller": SELLER,
                "nft": {"address": ITEM},
            }
        )
        is None
    )


def test_slugify() -> None:
    assert slugify("Anonymous Telegram Numbers") == "anonymous-telegram-numbers"
    assert slugify("  !!!  ") == "collection"
