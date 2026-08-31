"""Нормализация сырых ответов GetGems → доменные модели.

Чистые функции без I/O и без float: на входе — dict'ы из JSON, на выходе —
доменные объекты. Схема GetGems версионируется, поэтому чтение полей
защитное: каждый ``parse_*`` возвращает ``None`` на битой записи, а конвейер
логирует и пропускает её, не роняя всю пачку (ТЗ §3: «API маркетплейса
используется для скорости», падение одного элемента недопустимо).
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any

from nftsniper.contexts.sources.domain.collection import Collection
from nftsniper.contexts.sources.domain.item import Item, Trait, TraitSet
from nftsniper.contexts.sources.domain.listing import Listing
from nftsniper.contexts.sources.domain.marketplace import Marketplace
from nftsniper.contexts.sources.domain.sale import SaleEvent
from nftsniper.shared.money import TONAmount
from nftsniper.shared.ton_address import TonAddress, TonAddressError, parse_address

_NON_SLUG = re.compile(r"[^a-z0-9]+")


def _text(*values: Any) -> str | None:
    for value in values:
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _int_or_none(value: Any) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        try:
            return int(value.strip())
        except ValueError:
            return None
    return None


def _nano(value: Any) -> int | None:
    """Цена в nanoTON: int или строка цифр; отрицательное/нечисло → None."""
    nano = _int_or_none(value)
    if nano is None or nano < 0:
        return None
    return nano


def _iso(value: Any) -> datetime | None:
    text = _text(value)
    if text is None:
        return None
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def _address(value: Any) -> TonAddress | None:
    text = _text(value)
    if text is None:
        return None
    try:
        return parse_address(text)
    except TonAddressError:
        return None


def _first(node: dict[str, Any], *keys: str) -> Any:
    """Первое непустое значение из цепочки fallback-ключей."""
    for key in keys:
        value = node.get(key)
        if value not in (None, ""):
            return value
    return None


def slugify(name: str) -> str:
    slug = _NON_SLUG.sub("-", name.lower()).strip("-")
    return slug or "collection"


def parse_collection(node: dict[str, Any]) -> Collection | None:
    """``nftCollectionByAddress`` → Collection. None, если нет адреса."""
    address = _text(node.get("address"))
    if address is None:
        return None
    meta = node.get("meta")
    meta = meta if isinstance(meta, dict) else {}
    name = _text(meta.get("name"), node.get("name"))
    if name is None:
        name = f"Collection {address[:8]}"
    items_count = _int_or_none(node.get("nextItemIndex")) or 0
    return Collection(
        id=address,
        name=name,
        slug=slugify(name),
        marketplace=Marketplace.GETGEMS,
        verified=bool(node.get("verified")),
        items_count=items_count,
    )


def parse_item(node: dict[str, Any]) -> Item | None:
    """Узел NftItem → Item (трейты, без редкости — её считает)."""
    address = _text(node.get("address"))
    if address is None:
        return None
    index = _int_or_none(node.get("index")) or 0
    collection_id = _text(node.get("collectionAddress")) or ""
    name = _text(node.get("name")) or f"#{index}"

    traits: list[Trait] = []
    attributes = node.get("attributes")
    if isinstance(attributes, list):
        for attribute in attributes:
            if not isinstance(attribute, dict):
                continue
            trait_name = _text(attribute.get("traitType"))
            trait_value = _text(attribute.get("value"))
            if trait_name is not None and trait_value is not None:
                traits.append(Trait(name=trait_name, value=trait_value))

    return Item(
        id=address,
        collection_id=collection_id,
        index=index,
        name=name,
        traits=TraitSet(traits=tuple(traits)),
    )


def parse_listing(item_node: dict[str, Any], sale_node: dict[str, Any]) -> Listing | None:
    """Пара (item, sale) → Listing. None, если нет цены или продавца."""
    item = parse_item(item_node)
    if item is None:
        return None
    price_nano = _nano(_first(sale_node, "fullPrice", "price", "maxBid", "minBid"))
    if price_nano is None:
        return None
    seller = _address(_first(sale_node, "owner", "seller")) or _address(
        item_node.get("ownerAddress")
    )
    if seller is None:
        return None
    external_id = _text(sale_node.get("address")) or item.id
    listed_at = _iso(_first(sale_node, "createdAt", "listedAt"))
    return Listing(
        id=f"getgems:{external_id}",
        external_id=external_id,
        marketplace=Marketplace.GETGEMS,
        item=item,
        price=TONAmount.from_nano(price_nano),
        seller=seller,
        currency="ton",
        listed_at=listed_at,
        raw={"sale": sale_node, "item": item_node},
    )


def parse_sale(node: dict[str, Any], *, collection_address: str | None = None) -> SaleEvent | None:
    """Узел истории продаж → SaleEvent. None, если битая запись."""
    tx_hash = _text(node.get("txHash"), node.get("address"))
    if tx_hash is None:
        return None
    price_nano = _nano(_first(node, "price", "fullPrice", "maxBid", "minBid"))
    if price_nano is None:
        return None
    sold_at = _iso(_first(node, "timestamp", "createdAt", "soldAt"))
    if sold_at is None:
        return None
    nft = node.get("nft")
    nft = nft if isinstance(nft, dict) else {}
    item_id = _text(nft.get("address"), node.get("nftAddress"))
    if item_id is None:
        return None
    collection_id = collection_address or _text(nft.get("collectionAddress")) or ""
    buyer = _address(_first(node, "buyer", "to", "buyerAddress"))
    seller = _address(_first(node, "seller", "owner", "from", "sellerAddress"))
    if buyer is None or seller is None:
        return None
    return SaleEvent(
        id=tx_hash,
        item_id=item_id,
        collection_id=collection_id,
        price=TONAmount.from_nano(price_nano),
        buyer=buyer,
        seller=seller,
        tx_hash=tx_hash,
        sold_at=sold_at,
        marketplace=Marketplace.GETGEMS,
    )
