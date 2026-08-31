"""Контрактные тесты FragmentAdapter на записанных фикстурах (ТЗ §7).

Два источника за фикстурами: TonAPI (``tests/fixtures/tonapi/fragment_*.json``)
и fragment.com (``tests/fixtures/fragment/*.html`` — реальные строки live-страниц).
Хендлер MockTransport раздаёт их по хосту и пути.

Критерии готовности:
- источник отключается флагом (``enabled=False`` — ноль запросов);
- падение источника не ломает остальные (деградация ``list_auctions``);
- on-chain первичен, парсинг — fallback/дополнение;
- rate limit и TTL-кэш.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

import httpx
from tests.fakes import FakeChainPort

from nftsniper.contexts.sources.adapters.fragment import FragmentAdapter
from nftsniper.contexts.sources.domain.chain import NftTransfer
from nftsniper.contexts.sources.domain.fragment import FragmentKind, FragmentStatus
from nftsniper.contexts.sources.domain.marketplace import Marketplace
from nftsniper.infrastructure.http.client import ResilientHttpClient
from nftsniper.shared.money import TONAmount
from nftsniper.shared.ton_address import parse_address

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
FRAG = FIXTURES / "fragment"
TON = FIXTURES / "tonapi"

NUMBERS = "0:4cac1688d0ed22d0a3db653285812b33d8c23fa9220c0dde5f7ab056b27e17cf"
USERNAMES = "0:80d78a35f955a14b679faa887ff4cd5bfc0f43b4a4eea2a7e6927f3701b273c0"
N1 = "0:6b6fb936d922d194f3b2cce1babc2eca2ab75a1a9333111cb8524b4e2c856184"
N2 = "0:7fc834228cd0ff90cc1af82659dc176a4b6d575ad155edf80276327932abfdf2"
U1 = "0:000000000000000000000000000000000000000000000000000000000000010a"
U2 = "0:000000000000000000000000000000000000000000000000000000000000010b"
SELLER = "0:0000000000000000000000000000000000000000000000000000000000000aa1"
BUYER = "0:0000000000000000000000000000000000000000000000000000000000000bb2"

COLLECTIONS = {NUMBERS: FragmentKind.NUMBER, USERNAMES: FragmentKind.USERNAME}


def _load(name: str) -> dict[str, Any]:
    return cast(dict[str, Any], json.loads((TON / name).read_text(encoding="utf-8")))


def _item_map() -> dict[str, dict[str, Any]]:
    mapping: dict[str, dict[str, Any]] = {}
    for bulk_name in ("fragment_numbers_bulk.json", "fragment_usernames_bulk.json"):
        for item in _load(bulk_name)["nft_items"]:
            mapping[item["address"]] = item
    return mapping


def _items_fixture(address: str) -> dict[str, Any]:
    if address in (N1, N2, NUMBERS):
        return _load("fragment_numbers_items.json")
    if address in (U1, U2, USERNAMES):
        return _load("fragment_usernames_items.json")
    return {"nft_items": []}


def _transport(
    *,
    tonapi_fail: bool = False,
    fragment_fail: bool = False,
) -> tuple[httpx.MockTransport, list[httpx.Request]]:
    item_map = _item_map()
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return _route(request, item_map, tonapi_fail=tonapi_fail, fragment_fail=fragment_fail)

    return httpx.MockTransport(handler), captured


def _route(
    request: httpx.Request,
    item_map: dict[str, dict[str, Any]],
    *,
    tonapi_fail: bool,
    fragment_fail: bool,
) -> httpx.Response:
    host = request.url.host
    path = request.url.path
    if host == "fragment.com":
        return _route_fragment(path, fragment_fail=fragment_fail)
    if host == "tonapi.io":
        return _route_tonapi(request, path, item_map, tonapi_fail=tonapi_fail)
    return httpx.Response(404)


def _route_fragment(path: str, *, fragment_fail: bool) -> httpx.Response:
    if fragment_fail:
        return httpx.Response(500)
    name = "numbers.html" if path == "/numbers" else "usernames.html"
    return httpx.Response(200, text=(FRAG / name).read_text(encoding="utf-8"))


def _route_tonapi(
    request: httpx.Request,
    path: str,
    item_map: dict[str, dict[str, Any]],
    *,
    tonapi_fail: bool,
) -> httpx.Response:
    if tonapi_fail:
        return httpx.Response(500)
    segments = list(filter(None, path.split("/")))
    if path == "/v2/nfts/_bulk":
        body = json.loads(request.content)
        wanted = list(body.get("account_ids", []))
        found = [item_map[a] for a in wanted if a in item_map]
        return httpx.Response(200, json={"nft_items": found})
    if path.startswith("/v2/nfts/collections/") and path.endswith("/items"):
        return httpx.Response(200, json=_items_fixture(segments[-2]))
    if path.startswith("/v2/nfts/"):
        item = item_map.get(segments[-1])
        if item is None:
            return httpx.Response(404, json={"error": "item not found"})
        return httpx.Response(200, json=item)
    return httpx.Response(404, json={"error": "not found"})


def _adapter(
    transport: httpx.AsyncBaseTransport,
    *,
    enabled: bool = True,
    prefer_on_chain: bool = True,
    api_key: str | None = None,
    rate_limiter: Any = None,
    cache_ttl_seconds: int = 60,
    chain: FakeChainPort | None = None,
) -> FragmentAdapter:
    http = ResilientHttpClient(client=httpx.AsyncClient(transport=transport), max_retries=0)
    return FragmentAdapter(
        chain=chain if chain is not None else FakeChainPort(),
        http=http,
        endpoint="https://fragment.com",
        tonapi_endpoint="https://tonapi.io",
        api_key=api_key,
        enabled=enabled,
        prefer_on_chain=prefer_on_chain,
        rate_limiter=rate_limiter,
        cache_ttl_seconds=cache_ttl_seconds,
        collections=dict(COLLECTIONS),
    )


class _SpyLimiter:
    def __init__(self) -> None:
        self.calls = 0

    async def acquire(self) -> None:
        self.calls += 1


# ── флаг отключения ─────────────────────────────────────────────────────


async def test_disabled_makes_no_requests() -> None:
    transport, captured = _transport()
    adapter = _adapter(transport, enabled=False)
    assert await adapter.get_asset(U1) is None
    assert await adapter.list_assets(USERNAMES) == []
    assert await adapter.list_auctions(USERNAMES) == []
    assert await adapter.get_sales(U1) == []
    assert captured == []  # ни одного запроса
    await adapter.aclose()


# ── on-chain: активы и продажи ──────────────────────────────────────────


async def test_get_asset_on_chain() -> None:
    transport, _ = _transport()
    adapter = _adapter(transport)
    asset = await adapter.get_asset(U1)
    assert asset is not None
    assert asset.name == "blackhat"
    assert asset.kind is FragmentKind.USERNAME
    assert asset.collection_id == USERNAMES
    assert asset.owner is not None
    await adapter.aclose()


async def test_get_asset_accepts_user_friendly_and_404() -> None:
    transport, _ = _transport()
    adapter = _adapter(transport)
    user_friendly = parse_address(U1).user_friendly()
    assert await adapter.get_asset(user_friendly) is not None
    assert (
        await adapter.get_asset(
            "0:00000000000000000000000000000000000000000000000000000000000000ff"
        )
        is None
    )
    await adapter.aclose()


async def test_list_assets_enumerates_and_names() -> None:
    transport, _ = _transport()
    adapter = _adapter(transport)
    assets = await adapter.list_assets(NUMBERS)
    assert [asset.name for asset in assets] == ["+888 0000 1312", "+888 0707 7007"]
    assert [asset.kind for asset in assets] == [FragmentKind.NUMBER, FragmentKind.NUMBER]
    assert all(asset.owner is not None for asset in assets)
    await adapter.aclose()


async def test_get_sales_from_onchain_transfers() -> None:
    transport, _ = _transport()
    chain = FakeChainPort(
        transfers=[
            NftTransfer(
                tx_hash="tx-1",
                nft_address=N1,
                from_address=SELLER,
                to_address=BUYER,
                timestamp=datetime(2026, 8, 20, tzinfo=UTC),
                amount=TONAmount.from_ton(10),
            ),
            NftTransfer(
                tx_hash="tx-2",
                nft_address=N1,
                from_address=SELLER,
                to_address=BUYER,
                timestamp=datetime(2026, 8, 21, tzinfo=UTC),
                amount=None,  # дарение — не продажа
            ),
        ]
    )
    adapter = _adapter(transport, chain=chain)
    sales = await adapter.get_sales(N1)
    assert len(sales) == 1
    sale = sales[0]
    assert sale.price == TONAmount.from_ton(10)
    assert sale.marketplace is Marketplace.FRAGMENT
    assert sale.collection_id == NUMBERS
    assert sale.item_id == N1
    await adapter.aclose()


# ── list_auctions: слияние on-chain и scrape ────────────────────────────


async def test_list_auctions_merges_onchain_and_scrape() -> None:
    transport, _ = _transport()
    adapter = _adapter(transport)
    auctions = await adapter.list_auctions(USERNAMES)
    assert len(auctions) == 3
    blackhat = auctions[0]
    assert blackhat.asset.name == "blackhat"  # on-chain имя (без «@»)
    assert blackhat.asset.address == U1  # on-chain адрес подхвачен
    assert blackhat.asset.owner is not None
    assert blackhat.price == TONAmount.from_ton(35504)
    assert blackhat.status is FragmentStatus.RESALE
    # «@feds» есть на fragment.com, но нет в on-chain фикстуре
    feds = auctions[2]
    assert feds.asset.name == "@feds"
    assert feds.asset.address == ""
    assert feds.price == TONAmount.from_ton(23665)
    await adapter.aclose()


async def test_list_auctions_degrades_on_scrape_failure() -> None:
    """ТЗ §7: падение парсинга не ломает источник — цены None, активы on-chain."""
    transport, _ = _transport(fragment_fail=True)
    adapter = _adapter(transport)
    auctions = await adapter.list_auctions(USERNAMES)
    assert len(auctions) == 2  # только on-chain активы
    assert all(auction.price is None for auction in auctions)
    assert [auction.asset.name for auction in auctions] == ["blackhat", "board"]
    await adapter.aclose()


async def test_list_auctions_falls_back_to_scrape_when_onchain_fails() -> None:
    """ТЗ §7: on-chain упал → парсинг как fallback (без on-chain адресов)."""
    transport, _ = _transport(tonapi_fail=True)
    adapter = _adapter(transport)
    auctions = await adapter.list_auctions(USERNAMES)
    assert len(auctions) == 3
    assert all(auction.asset.address == "" for auction in auctions)
    assert auctions[0].price == TONAmount.from_ton(35504)
    await adapter.aclose()


async def test_list_auctions_unknown_collection_returns_empty() -> None:
    transport, captured = _transport()
    adapter = _adapter(transport)
    assert await adapter.list_auctions("0:unknowncollection") == []
    assert captured == []
    await adapter.aclose()


async def test_prefer_on_chain_false_skips_tonapi() -> None:
    transport, captured = _transport()
    adapter = _adapter(transport, prefer_on_chain=False)
    auctions = await adapter.list_auctions(USERNAMES)
    assert len(auctions) == 3
    assert all(request.url.host == "fragment.com" for request in captured)
    await adapter.aclose()


# ── кэш и rate limit ────────────────────────────────────────────────────


async def test_scrape_is_cached() -> None:
    transport, captured = _transport()
    adapter = _adapter(transport, cache_ttl_seconds=600)
    await adapter.list_auctions(USERNAMES)
    await adapter.list_auctions(USERNAMES)
    fragment_requests = [request for request in captured if request.url.host == "fragment.com"]
    assert len(fragment_requests) == 1  # вторая выборка из кэша
    await adapter.aclose()


async def test_rate_limiter_acquired_per_request() -> None:
    transport, _ = _transport()
    limiter = _SpyLimiter()
    adapter = _adapter(transport, rate_limiter=limiter)
    await adapter.get_asset(U1)
    assert limiter.calls == 1
    await adapter.list_assets(USERNAMES)  # items + bulk
    assert limiter.calls == 3
    await adapter.aclose()


async def test_bearer_header_sent_to_tonapi() -> None:
    seen: list[dict[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(dict(request.headers))
        if request.url.path.startswith("/v2/nfts/"):
            return httpx.Response(404, json={"error": "item not found"})
        return httpx.Response(200, json={"nft_items": []})

    transport = httpx.MockTransport(handler)
    adapter = _adapter(transport, api_key="secret-key")
    await adapter.get_asset(U1)
    assert seen
    assert seen[0].get("authorization") == "Bearer secret-key"
    await adapter.aclose()
