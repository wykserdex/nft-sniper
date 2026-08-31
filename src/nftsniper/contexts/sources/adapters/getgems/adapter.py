"""GetGems Adapter: реализация MarketplacePort поверх GraphQL GetGems.

Пайплайн: POST {endpoint} (GraphQL) → нормализация → доменные модели.

- retry + circuit breaker — через ``ResilientHttpClient`` (infrastructure.http);
- rate limit — ``RateLimiter`` перед каждым запросом;
- пагинация: листинги — offset; продажи — offset + фильтр ``since`` (продажи
  приходят newest-first);
- ``raw`` каждого листинга хранит исходные узлы для аудита и сверки с chain
  (ТЗ §3: расхождение >1% помечается флагом — делает).

Транспортные ошибки (``HttpError``, ``CircuitBreakerOpenError``) намеренно не
оборачиваются: их уже несёт ResilientHttpClient, и конвейер различает
«источник недоступен» и «источник ответил ошибкой» (``GetGemsError``).
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

from nftsniper.contexts.sources.adapters.getgems.exceptions import (
    GetGemsGraphQLError,
    GetGemsResponseError,
)
from nftsniper.contexts.sources.adapters.getgems.normalizer import (
    parse_collection,
    parse_item,
    parse_listing,
    parse_sale,
)
from nftsniper.contexts.sources.adapters.getgems.queries import (
    COLLECTION_QUERY,
    ITEM_QUERY,
    LISTINGS_QUERY,
    SALES_QUERY,
)
from nftsniper.contexts.sources.domain.collection import Collection
from nftsniper.contexts.sources.domain.item import Item
from nftsniper.contexts.sources.domain.listing import Listing
from nftsniper.contexts.sources.domain.sale import SaleEvent
from nftsniper.infrastructure.http.client import ResilientHttpClient
from nftsniper.infrastructure.http.ratelimit import RateLimiter
from nftsniper.observability.logging import get_logger

# Защита от бесконечного цикла при поломанной пагинации источника.
_MAX_LISTING_PAGES = 100


class GetGemsAdapter:
    """Реализация ``MarketplacePort`` для маркетплейса GetGems."""

    def __init__(
        self,
        *,
        http: ResilientHttpClient,
        endpoint: str,
        api_key: str | None = None,
        rate_limiter: RateLimiter | None = None,
        page_size: int = 100,
    ) -> None:
        self._http = http
        self._endpoint = endpoint
        self._api_key = api_key
        self._limiter = rate_limiter
        self._page_size = page_size
        self._log = get_logger(__name__, source="getgems")

    async def get_collection(self, address: str) -> Collection | None:
        data = await self._graphql(COLLECTION_QUERY, {"address": address}, "GetGemsCollection")
        node = data.get("nftCollectionByAddress")
        if not isinstance(node, dict) or not node:
            return None
        return parse_collection(node)

    async def get_item(self, address: str) -> Item | None:
        data = await self._graphql(ITEM_QUERY, {"addresses": [address]}, "GetGemsItem")
        nodes = data.get("nftItemsByAddresses")
        if not isinstance(nodes, list) or not nodes:
            return None
        first = nodes[0]
        return parse_item(first) if isinstance(first, dict) else None

    async def list_active_listings(
        self,
        collection_address: str | None = None,
        limit: int = 100,
    ) -> Sequence[Listing]:
        """Активные листинги коллекции (сортировка: цена asc).

        GetGems не отдаёт «все листинги» одним запросом — ``collection_address``
        обязателен; для ``None`` поднимается ValueError (явный контракт).
        """
        if collection_address is None:
            msg = "GetGems не отдаёт «все листинги» одним запросом: укажите collection_address"
            raise ValueError(msg)
        if limit <= 0:
            return []

        page_size = min(self._page_size, limit)
        collected: list[Listing] = []
        offset = 0
        for _ in range(_MAX_LISTING_PAGES):
            data = await self._graphql(
                LISTINGS_QUERY,
                {"address": collection_address, "limit": page_size, "offset": offset},
                "GetGemsListings",
            )
            result = data.get("getNftItemsByCollectionOnSale")
            nodes = self._items_of(result)
            if not nodes:
                break
            for node in nodes:
                if len(collected) >= limit:
                    return collected
                listing = self._parse_listing_node(node)
                if listing is not None:
                    collected.append(listing)
                else:
                    self._log.warning("getgems.skip_listing", node=json.dumps(node)[:400])
            offset += page_size
            if len(nodes) < page_size:
                break
        return collected

    async def get_sales(
        self,
        collection_address: str,
        since: datetime,
        limit: int = 500,
        until: datetime | None = None,
    ) -> Sequence[SaleEvent]:
        """Продажи коллекции с ``since`` (newest-first), не позже ``until``.

        Дедупликация по tx_hash внутри пачек; даты без tz трактуются как UTC.
        """
        if limit <= 0:
            return []
        since_utc = since if since.tzinfo is not None else since.replace(tzinfo=UTC)
        until_utc = None
        if until is not None:
            until_utc = until if until.tzinfo is not None else until.replace(tzinfo=UTC)
        page_size = min(self._page_size, limit)

        collected: list[SaleEvent] = []
        seen: set[str] = set()
        offset = 0
        exhausted = False
        while len(collected) < limit and not exhausted:
            data = await self._graphql(
                SALES_QUERY,
                {"collectionAddress": collection_address, "limit": page_size, "offset": offset},
                "GetGemsSales",
            )
            nodes = data.get("nftSalesOnCollection")
            if not isinstance(nodes, list) or not nodes:
                break
            for node in nodes:
                if not isinstance(node, dict):
                    continue
                sale = parse_sale(node, collection_address=collection_address)
                if sale is None:
                    self._log.warning("getgems.skip_sale", node=json.dumps(node)[:400])
                    continue
                if sale.sold_at < since_utc:
                    exhausted = True  # newest-first: дальше только старше
                    break
                if until_utc is not None and sale.sold_at > until_utc:
                    continue  # новее верхней границы окна — пропускаем
                if sale.id not in seen:
                    seen.add(sale.id)
                    collected.append(sale)
                if len(collected) >= limit:
                    break
            offset += page_size
            if len(nodes) < page_size:
                break
        return collected

    async def aclose(self) -> None:
        await self._http.aclose()

    # ── внутренние ──────────────────────────────────────────────────────

    @staticmethod
    def _items_of(result: Any) -> list[Any]:
        """Ответ листингов бывает ``{items: [...], cursor}`` либо списком."""
        if isinstance(result, dict):
            items = result.get("items")
            return items if isinstance(items, list) else []
        if isinstance(result, list):
            return result
        return []

    def _parse_listing_node(self, node: object) -> Listing | None:
        if not isinstance(node, dict):
            return None
        sale = node.get("sale")
        if not isinstance(sale, dict):
            return None
        return parse_listing(node, sale)

    async def _graphql(
        self,
        query: str,
        variables: dict[str, Any],
        operation_name: str,
    ) -> dict[str, Any]:
        if self._limiter is not None:
            await self._limiter.acquire()
        headers = {"Content-Type": "application/json"}
        if self._api_key is not None:
            headers["X-API-KEY"] = self._api_key
        body = {"query": query, "variables": variables, "operationName": operation_name}
        payload = await self._http.post_json(self._endpoint, json=body, headers=headers)
        if not isinstance(payload, dict):
            msg = (
                f"GetGems ({operation_name}): ожидался JSON-объект, "
                f"получено {type(payload).__name__}"
            )
            raise GetGemsResponseError(msg)
        errors = payload.get("errors")
        if errors:
            raise GetGemsGraphQLError(errors if isinstance(errors, list) else [errors])
        data = payload.get("data")
        if not isinstance(data, dict):
            msg = f"GetGems ({operation_name}): в ответе отсутствует data"
            raise GetGemsResponseError(msg)
        return data
