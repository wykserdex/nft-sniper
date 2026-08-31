"""Контрактные тесты GetGemsAdapter на записанных фикстурах (ТЗ §7).

Живой GraphQL GetGems закрыт API-ключом, поэтому ответы записаны в
tests/fixtures/getgems/*.json; хендлер MockTransport отдаёт их и эмулирует
пагинацию (срез по offset/limit) так же, как реальный источник.

Критерий готовности: эти тесты проходят на фикстурах, а адаптер
заменяем на fake без изменений в use cases (см. последний тест).
"""

from __future__ import annotations

import copy
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

import httpx
import pytest
from tests.fakes import InMemoryListingRepository

from nftsniper.contexts.sources.adapters.getgems import GetGemsAdapter, GetGemsGraphQLError
from nftsniper.contexts.sources.application import PollListings
from nftsniper.infrastructure.http.client import HttpError, ResilientHttpClient

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "getgems"
COLL = "EQChoaGhoaGhoaGhoaGhoaGhoaGhoaGhoaGhoaGhoaGhodWi"


def _load(name: str) -> dict[str, Any]:
    return cast(dict[str, Any], json.loads((FIXTURES / name).read_text(encoding="utf-8")))


def _transport() -> tuple[httpx.MockTransport, list[dict[str, Any]]]:
    """MockTransport поверх фикстур + срез списочных операций по offset/limit."""
    responses = {
        "GetGemsCollection": _load("collection.json"),
        "GetGemsItem": _load("item.json"),
        "GetGemsListings": _load("listings.json"),
        "GetGemsSales": _load("sales.json"),
    }
    captured: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        captured.append(body)
        operation = body.get("operationName")
        payload = copy.deepcopy(responses[operation])
        variables = body.get("variables") or {}
        offset = int(variables.get("offset") or 0)
        limit = int(variables.get("limit") or 100)
        data = payload.get("data") or {}
        if operation == "GetGemsListings":
            node = data.get("getNftItemsByCollectionOnSale")
            if isinstance(node, dict) and isinstance(node.get("items"), list):
                node["items"] = node["items"][offset : offset + limit]
        elif operation == "GetGemsSales":
            node = data.get("nftSalesOnCollection")
            if isinstance(node, list):
                data["nftSalesOnCollection"] = node[offset : offset + limit]
        return httpx.Response(200, json=payload)

    return httpx.MockTransport(handler), captured


def _adapter(
    transport: httpx.AsyncBaseTransport,
    *,
    api_key: str | None = None,
    page_size: int = 100,
    rate_limiter: Any = None,
) -> GetGemsAdapter:
    http = ResilientHttpClient(client=httpx.AsyncClient(transport=transport), max_retries=0)
    return GetGemsAdapter(
        http=http,
        endpoint="https://api.getgems.io/graphql",
        api_key=api_key,
        rate_limiter=rate_limiter,
        page_size=page_size,
    )


class _SpyLimiter:
    """Считает вызовы acquire — доказывает, что лимит соблюдается перед запросом."""

    def __init__(self) -> None:
        self.calls = 0

    async def acquire(self) -> None:
        self.calls += 1


# ── коллекции / предметы ────────────────────────────────────────────────


async def test_get_collection() -> None:
    transport, captured = _transport()
    adapter = _adapter(transport)
    collection = await adapter.get_collection(COLL)
    assert collection is not None
    assert collection.name == "Anonymous Telegram Numbers"
    assert collection.items_count == 10000
    assert collection.verified is True
    assert collection.marketplace is not None
    assert collection.marketplace.value == "getgems"
    assert captured[0]["operationName"] == "GetGemsCollection"
    await adapter.aclose()


async def test_get_collection_not_found_returns_none() -> None:
    transport = httpx.MockTransport(
        lambda req: httpx.Response(200, json={"data": {"nftCollectionByAddress": None}})
    )
    adapter = _adapter(transport)
    assert await adapter.get_collection(COLL) is None
    await adapter.aclose()


async def test_get_item_with_traits() -> None:
    transport, _ = _transport()
    adapter = _adapter(transport)
    item = await adapter.get_item("EQDBwcHBwcHBwcHBwcHBwcHBwcHBwcHBwcHBwcHBwcHBwS2C")
    assert item is not None
    assert item.index == 888
    number = item.traits.get("Number")
    assert number is not None
    assert number.value == "888"
    await adapter.aclose()


async def test_get_item_not_found() -> None:
    transport = httpx.MockTransport(
        lambda req: httpx.Response(200, json={"data": {"nftItemsByAddresses": []}})
    )
    adapter = _adapter(transport)
    assert await adapter.get_item("x") is None
    await adapter.aclose()


# ── листинги ────────────────────────────────────────────────────────────


async def test_list_active_listings_paginates_and_skips_unpriced() -> None:
    transport, captured = _transport()
    adapter = _adapter(transport, page_size=2)
    listings = await adapter.list_active_listings(COLL, limit=100)
    assert [listing.price.formatted for listing in listings] == ["120", "130", "150", "99"]
    # пагинация offset: 0 → 2 → 4 (5 узлов, из них 1 без sale — пропущен)
    offsets = [int(c["variables"]["offset"]) for c in captured]
    assert offsets == [0, 2, 4]
    await adapter.aclose()


async def test_list_active_listings_respects_limit() -> None:
    transport, captured = _transport()
    adapter = _adapter(transport, page_size=2)
    listings = await adapter.list_active_listings(COLL, limit=3)
    assert len(listings) == 3
    offsets = [int(c["variables"]["offset"]) for c in captured]
    assert offsets == [0, 2]  # лишние страницы не читаются
    await adapter.aclose()


async def test_list_active_listings_requires_collection() -> None:
    transport, _ = _transport()
    adapter = _adapter(transport)
    with pytest.raises(ValueError, match="collection_address"):
        await adapter.list_active_listings(None)
    await adapter.aclose()


async def test_list_active_listings_zero_limit_no_requests() -> None:
    transport, captured = _transport()
    adapter = _adapter(transport)
    assert await adapter.list_active_listings(COLL, limit=0) == []
    assert captured == []
    await adapter.aclose()


# ── продажи ─────────────────────────────────────────────────────────────


async def test_get_sales_filters_since() -> None:
    transport, _ = _transport()
    adapter = _adapter(transport)
    sales = await adapter.get_sales(COLL, datetime(2026, 8, 30, tzinfo=UTC), limit=100)
    assert [sale.id for sale in sales] == ["tx-s1", "tx-s2"]
    assert [sale.price.formatted for sale in sales] == ["214", "205"]
    await adapter.aclose()


async def test_get_sales_paginates() -> None:
    transport, captured = _transport()
    adapter = _adapter(transport, page_size=2)
    sales = await adapter.get_sales(COLL, datetime(2026, 8, 28, tzinfo=UTC), limit=100)
    assert [sale.id for sale in sales] == ["tx-s1", "tx-s2", "tx-s3", "tx-s4"]
    offsets = [int(c["variables"]["offset"]) for c in captured]
    assert offsets == [0, 2, 4]
    await adapter.aclose()


async def test_get_sales_respects_until_upper_bound() -> None:
    transport, _ = _transport()
    adapter = _adapter(transport)
    sales = await adapter.get_sales(
        COLL,
        datetime(2026, 8, 28, tzinfo=UTC),
        limit=100,
        until=datetime(2026, 8, 31, tzinfo=UTC),
    )
    # s1 (10:00 31-го) новее until → пропущен
    assert [sale.id for sale in sales] == ["tx-s2", "tx-s3", "tx-s4"]
    await adapter.aclose()


async def test_get_sales_stops_at_older_than_since() -> None:
    transport, captured = _transport()
    adapter = _adapter(transport, page_size=2)
    sales = await adapter.get_sales(COLL, datetime(2026, 8, 30, tzinfo=UTC), limit=100)
    assert [sale.id for sale in sales] == ["tx-s1", "tx-s2"]
    # полная страница → вторая запрошена; найдена продажа старше since → стоп
    offsets = [int(c["variables"]["offset"]) for c in captured]
    assert offsets == [0, 2]
    await adapter.aclose()


# ── ошибки и транспорт ──────────────────────────────────────────────────


async def test_graphql_errors_raise() -> None:
    transport = httpx.MockTransport(
        lambda req: httpx.Response(200, json={"errors": [{"message": "boom"}], "data": None})
    )
    adapter = _adapter(transport)
    with pytest.raises(GetGemsGraphQLError, match="boom"):
        await adapter.get_collection(COLL)
    await adapter.aclose()


async def test_http_error_propagates() -> None:
    transport = httpx.MockTransport(lambda req: httpx.Response(503))
    adapter = _adapter(transport)
    with pytest.raises(HttpError):
        await adapter.get_collection(COLL)
    await adapter.aclose()


async def test_api_key_header_sent() -> None:
    seen: list[dict[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(dict(request.headers))
        return httpx.Response(200, json={"data": {"nftCollectionByAddress": None}})

    adapter = _adapter(httpx.MockTransport(handler), api_key="secret-key")
    await adapter.get_collection(COLL)
    assert seen[0].get("x-api-key") == "secret-key"
    await adapter.aclose()


async def test_rate_limiter_acquired_before_each_request() -> None:
    transport, _ = _transport()
    limiter = _SpyLimiter()
    adapter = _adapter(transport, rate_limiter=limiter)
    await adapter.get_collection(COLL)
    await adapter.get_item("x")
    assert limiter.calls == 2
    await adapter.aclose()


# ── заменяемость: адаптер в use case, который знает только порт ─────────


def test_adapter_exposes_marketplace_port_methods() -> None:
    for name in ("get_collection", "get_item", "list_active_listings", "get_sales"):
        assert callable(getattr(GetGemsAdapter, name))


async def test_poll_listings_use_case_with_real_adapter() -> None:
    """Критерий: адаптер встаёт в use case, зависящий только от порта."""
    transport, _ = _transport()
    adapter = _adapter(transport, page_size=2)
    repository = InMemoryListingRepository()

    first = await PollListings(adapter, repository).run(COLL)
    assert first.discovered_count == 4
    assert len(first.events) == 4

    # повторный запуск: дедуп по dedup_key — новых листингов нет
    second = await PollListings(adapter, repository).run(COLL)
    assert second.discovered_count == 0
    await adapter.aclose()
