"""Fragment Adapter: реализация FragmentPort (on-chain первичен).

Два источника, чётко разделённые:

- **on-chain** (TonAPI REST + ``ChainPort``) — существование, имена, владельцы
  и реальные цены продаж (трансферы) юзернеймов/номеров; источник истины.
- **fragment.com** (парсинг HTML) — текущие ставки и цены аукционов
  (fallback/дополнение: это единственное место, где они видны).

Политика деградации (ТЗ §7):

- ``enabled=False`` — ни одного сетевого запроса (источник отключён флагом);
- сбой парсинга/транспорта fragment.com никогда не роняет конвейер:
  ``list_auctions`` возвращает частичный/пустой результат и логирует
  предупреждение; on-chain ошибки (кроме 404 → None) пробрасываются;
- парсинг идёт через rate limiter и TTL-кэш (частота ограничена, вёрстка
  читается защитно — см. scraper.py).
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping, Sequence
from datetime import datetime, timedelta
from typing import Any

from nftsniper.contexts.sources.adapters.fragment.scraper import ScrapedListing, parse_listings
from nftsniper.contexts.sources.application.clock import utcnow
from nftsniper.contexts.sources.domain.chain import NftTransfer
from nftsniper.contexts.sources.domain.fragment import (
    FragmentAsset,
    FragmentAuction,
    FragmentKind,
)
from nftsniper.contexts.sources.domain.marketplace import Marketplace
from nftsniper.contexts.sources.domain.sale import SaleEvent
from nftsniper.contexts.sources.ports import ChainPort
from nftsniper.contexts.sources.ports.fragment import FragmentScrapeError
from nftsniper.infrastructure.http.circuit_breaker import CircuitBreakerOpenError
from nftsniper.infrastructure.http.client import HttpError, ResilientHttpClient
from nftsniper.infrastructure.http.ratelimit import RateLimiter
from nftsniper.observability.logging import get_logger
from nftsniper.shared.money import TONAmount
from nftsniper.shared.ton_address import TonAddressError, parse_address

_HTTP_NOT_FOUND = 404
_MAX_BULK_ITEMS = 1000
_NAME_KEY_RE = re.compile(r"[+@\s]")

_COLLECTIONS_PATH: dict[FragmentKind, str] = {
    FragmentKind.USERNAME: "/",
    FragmentKind.NUMBER: "/numbers",
}


def _account_id(address: str) -> str:
    """Адрес → raw-форма ``0:hex`` для пути запроса (fallback: как есть)."""
    try:
        return parse_address(address).raw_str
    except (TonAddressError, ValueError):
        return address.strip()


def _name_key(name: str) -> str:
    """Нормализация имени для сопоставления scrape ↔ on-chain."""
    return _NAME_KEY_RE.sub("", name).lower()


def _asset_kind(name: str) -> FragmentKind:
    stripped = name.strip()
    if stripped.startswith("+"):
        return FragmentKind.NUMBER
    return FragmentKind.USERNAME


def parse_asset_node(
    node: dict[str, Any],
    *,
    kind: FragmentKind,
    fallback_collection: str,
) -> FragmentAsset | None:
    """Узел ``NftItem`` TonAPI → ``FragmentAsset``. None, если нет адреса/имени."""
    address = node.get("address")
    if not isinstance(address, str) or not address:
        return None
    metadata = node.get("metadata")
    name = metadata.get("name") if isinstance(metadata, dict) else None
    if not isinstance(name, str) or not name.strip():
        return None
    owner_node = node.get("owner")
    owner = None
    if isinstance(owner_node, dict) and isinstance(owner_node.get("address"), str):
        try:
            owner = parse_address(owner_node["address"])
        except (TonAddressError, ValueError):
            owner = None
    collection = node.get("collection")
    collection_id = fallback_collection
    if isinstance(collection, dict) and isinstance(collection.get("address"), str):
        collection_id = collection["address"]
    return FragmentAsset(
        address=address,
        name=name.strip(),
        kind=kind,
        collection_id=collection_id,
        owner=owner,
    )


class FragmentAdapter:
    """Реализация ``FragmentPort``: on-chain (TonAPI/ChainPort) + scrape (fragment.com)."""

    def __init__(
        self,
        *,
        chain: ChainPort,
        http: ResilientHttpClient,
        endpoint: str = "https://fragment.com",
        tonapi_endpoint: str = "https://tonapi.io",
        api_key: str | None = None,
        enabled: bool = True,
        prefer_on_chain: bool = True,
        rate_limiter: RateLimiter | None = None,
        cache_ttl_seconds: int = 60,
        page_size: int = 100,
        collections: Mapping[str, FragmentKind] | None = None,
        clock: Callable[[], datetime] = utcnow,
    ) -> None:
        self._chain = chain
        self._http = http
        self._endpoint = endpoint.rstrip("/")
        self._tonapi_endpoint = tonapi_endpoint.rstrip("/")
        self._api_key = api_key
        self._enabled = enabled
        self._prefer_on_chain = prefer_on_chain
        self._limiter = rate_limiter
        self._cache_ttl = timedelta(seconds=cache_ttl_seconds)
        self._cache_enabled = cache_ttl_seconds > 0
        self._page_size = page_size
        self._collections: dict[str, FragmentKind] = dict(collections or {})
        self._clock = clock
        self._cache: dict[str, tuple[datetime, str]] = {}
        self._log = get_logger(__name__, source="fragment")

    # ── on-chain ────────────────────────────────────────────────────────

    async def get_asset(self, address: str) -> FragmentAsset | None:
        if not self._enabled:
            return None
        node = await self._tonapi_item(address)
        if node is None:
            return None
        return parse_asset_node(
            node,
            kind=self._kind_for(node, requested_collection=None),
            fallback_collection="",
        )

    async def list_assets(
        self,
        collection_address: str,
        limit: int = 100,
    ) -> Sequence[FragmentAsset]:
        if not self._enabled:
            return []
        if limit <= 0:
            return []
        addresses = await self._tonapi_collection_items(collection_address, limit)
        kind = self._collections.get(collection_address, FragmentKind.USERNAME)
        assets: list[FragmentAsset] = []
        for offset in range(0, len(addresses), self._page_size):
            nodes = await self._tonapi_bulk(addresses[offset : offset + self._page_size])
            for node in nodes:
                asset = parse_asset_node(node, kind=kind, fallback_collection=collection_address)
                if asset is not None:
                    assets.append(asset)
                if len(assets) >= limit:
                    return assets[:limit]
        return assets[:limit]

    async def get_sales(
        self,
        asset_address: str,
        since: datetime | None = None,
        limit: int = 50,
    ) -> Sequence[SaleEvent]:
        if not self._enabled:
            return []
        if limit <= 0:
            return []
        asset = await self.get_asset(asset_address)
        if asset is None:
            return []
        transfers = await self._chain.get_nft_transfers(asset_address, since=since, limit=limit)
        sales: list[SaleEvent] = []
        for transfer in transfers:
            sale = self._transfer_to_sale(transfer, asset)
            if sale is not None:
                sales.append(sale)
        return sales

    # ── scrape ──────────────────────────────────────────────────────────

    async def list_auctions(
        self,
        collection_address: str,
        limit: int = 100,
    ) -> Sequence[FragmentAuction]:
        if not self._enabled:
            return []
        if limit <= 0:
            return []
        kind = self._collections.get(collection_address)
        if kind is None:
            self._log.warning("fragment.unknown_collection", collection=collection_address)
            return []
        assets_by_name, on_chain_ok = await self._load_onchain_assets(collection_address, limit)
        scraped = await self._load_scraped(kind, limit)
        return self._merge_auctions(scraped, assets_by_name, collection_address, limit, on_chain_ok)

    async def _load_onchain_assets(
        self,
        collection_address: str,
        limit: int,
    ) -> tuple[dict[str, FragmentAsset], bool]:
        assets_by_name: dict[str, FragmentAsset] = {}
        on_chain_ok = True
        if not self._prefer_on_chain:
            return assets_by_name, on_chain_ok
        try:
            for asset in await self.list_assets(collection_address, limit=limit):
                assets_by_name[_name_key(asset.name)] = asset
        except (HttpError, CircuitBreakerOpenError, FragmentScrapeError) as exc:
            on_chain_ok = False
            self._log.warning("fragment.onchain_failed", error=str(exc))
        return assets_by_name, on_chain_ok

    async def _load_scraped(self, kind: FragmentKind, limit: int) -> list[ScrapedListing]:
        try:
            return await self._scrape_listings(kind, limit)
        except (FragmentScrapeError, CircuitBreakerOpenError) as exc:
            self._log.warning("fragment.scrape_failed", error=str(exc))
            return []

    def _merge_auctions(
        self,
        scraped: Sequence[ScrapedListing],
        assets_by_name: dict[str, FragmentAsset],
        collection_address: str,
        limit: int,
        on_chain_ok: bool,
    ) -> list[FragmentAuction]:
        auctions: list[FragmentAuction] = []
        for entry in scraped:
            key = _name_key(entry.name)
            asset = assets_by_name.get(key)
            if asset is None:
                asset = FragmentAsset(
                    address="",
                    name=entry.name,
                    kind=entry.kind,
                    collection_id=collection_address,
                )
            auctions.append(
                FragmentAuction(
                    asset=asset,
                    price=TONAmount.from_nano(entry.price_nano)
                    if entry.price_nano is not None
                    else None,
                    ends_at=entry.ends_at,
                    status=entry.status,
                    external_id=entry.external_id,
                )
            )
        if len(auctions) >= limit:
            return auctions[:limit]
        if on_chain_ok:
            seen = {_name_key(auction.asset.name) for auction in auctions}
            for asset in assets_by_name.values():
                if _name_key(asset.name) in seen:
                    continue
                auctions.append(FragmentAuction(asset=asset))
                if len(auctions) >= limit:
                    break
        return auctions[:limit]

    async def aclose(self) -> None:
        await self._http.aclose()

    # ── внутренние: on-chain (TonAPI) ───────────────────────────────────

    async def _tonapi_item(self, address: str) -> dict[str, Any] | None:
        try:
            data = await self._tonapi_get(f"/v2/nfts/{_account_id(address)}")
        except HttpError as exc:
            if exc.status_code == _HTTP_NOT_FOUND:
                return None
            raise
        if not isinstance(data, dict):
            msg = f"TonAPI nft: ожидался объект, получено {type(data).__name__}"
            raise FragmentScrapeError(msg)
        return data

    async def _tonapi_collection_items(self, collection_address: str, limit: int) -> list[str]:
        data = await self._tonapi_get(
            f"/v2/nfts/collections/{_account_id(collection_address)}/items",
            params={"limit": min(limit, self._page_size, _MAX_BULK_ITEMS)},
        )
        if not isinstance(data, dict) or not isinstance(data.get("nft_items"), list):
            return []
        addresses: list[str] = []
        for item in data["nft_items"]:
            if isinstance(item, dict) and isinstance(item.get("address"), str):
                address = item["address"].strip()
                if address:
                    addresses.append(address)
        return addresses

    async def _tonapi_bulk(self, addresses: Sequence[str]) -> list[dict[str, Any]]:
        data = await self._tonapi_post("/v2/nfts/_bulk", body={"account_ids": list(addresses)})
        if not isinstance(data, dict) or not isinstance(data.get("nft_items"), list):
            return []
        return [item for item in data["nft_items"] if isinstance(item, dict)]

    async def _tonapi_get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        if self._limiter is not None:
            await self._limiter.acquire()
        return await self._http.get_json(
            f"{self._tonapi_endpoint}{path}", params=params, headers=self._headers()
        )

    async def _tonapi_post(self, path: str, body: dict[str, Any]) -> Any:
        if self._limiter is not None:
            await self._limiter.acquire()
        return await self._http.post_json(
            f"{self._tonapi_endpoint}{path}", json=body, headers=self._headers()
        )

    def _headers(self) -> dict[str, str]:
        if self._api_key is None:
            return {}
        return {"Authorization": f"Bearer {self._api_key}"}

    # ── внутренние: scrape (fragment.com) ───────────────────────────────

    async def _scrape_listings(self, kind: FragmentKind, limit: int) -> list[ScrapedListing]:
        path = _COLLECTIONS_PATH.get(kind, "/")
        html = await self._scrape_page(path)
        return parse_listings(html)[:limit]

    async def _scrape_page(self, path: str) -> str:
        url = f"{self._endpoint}{path}"
        cached = self._cache_get(url)
        if cached is not None:
            return cached
        if self._limiter is not None:
            await self._limiter.acquire()
        try:
            text = await self._http.get_text(url, headers={"User-Agent": "nft-sniper/0.1"})
        except (HttpError, CircuitBreakerOpenError) as exc:
            msg = f"fragment.com {path}: {exc}"
            raise FragmentScrapeError(msg) from exc
        self._cache_put(url, text)
        return text

    def _cache_get(self, url: str) -> str | None:
        entry = self._cache.get(url)
        if entry is None:
            return None
        expires_at, text = entry
        if self._clock() >= expires_at:
            self._cache.pop(url, None)
            return None
        return text

    def _cache_put(self, url: str, text: str) -> None:
        if not self._cache_enabled:
            return
        self._cache[url] = (self._clock() + self._cache_ttl, text)

    # ── внутренние: маппинги ────────────────────────────────────────────

    def _kind_for(
        self,
        node: dict[str, Any],
        *,
        requested_collection: str | None,
    ) -> FragmentKind:
        collection = node.get("collection")
        collection_address = collection.get("address") if isinstance(collection, dict) else None
        if isinstance(collection_address, str) and collection_address in self._collections:
            return self._collections[collection_address]
        if requested_collection is not None and requested_collection in self._collections:
            return self._collections[requested_collection]
        metadata = node.get("metadata")
        name = metadata.get("name") if isinstance(metadata, dict) else None
        if isinstance(name, str):
            return _asset_kind(name)
        return FragmentKind.USERNAME

    def _transfer_to_sale(
        self,
        transfer: NftTransfer,
        asset: FragmentAsset,
    ) -> SaleEvent | None:
        if transfer.amount is None:
            return None
        try:
            buyer = parse_address(transfer.to_address)
            seller = parse_address(transfer.from_address)
        except (TonAddressError, ValueError):
            return None
        return SaleEvent(
            id=transfer.tx_hash,
            item_id=transfer.nft_address or asset.address,
            collection_id=asset.collection_id,
            price=transfer.amount,
            buyer=buyer,
            seller=seller,
            tx_hash=transfer.tx_hash,
            sold_at=transfer.timestamp,
            marketplace=Marketplace.FRAGMENT,
        )
