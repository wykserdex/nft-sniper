"""Контрактные тесты TonapiChainAdapter на записанных фикстурах (ТЗ §7).

Фикстуры ``tests/fixtures/tonapi/*.json`` повторяют схему TonAPI REST v2
(``/v2/nfts/…``, ``/v2/accounts/…``). Хендлер MockTransport раздаёт их по
путям и эмулирует ``start_date``-фильтрацию истории. Критерий готовности
: on-chain цена сверяется с API-ценой на выборке сделок, расхождения
(>1%) помечаются флагом ``SaleVerification.matches=False``.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, cast

import httpx
import pytest

from nftsniper.contexts.sources.adapters.tonapi import (
    TonapiChainAdapter,
    TonapiResponseError,
)
from nftsniper.contexts.sources.domain.sale import SaleEvent
from nftsniper.infrastructure.http.client import ResilientHttpClient
from nftsniper.shared.money import TONAmount
from nftsniper.shared.ton_address import parse_address

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "tonapi"
NFT = "0:30ed366b91e98c93f9323aabfd8a97947d7b4524e28ccfb5d202f24abeee55c3"
OWNER = "0:759ade469adc736e3a96eb5201092738437855b6817472578e9f5bc76b5cb5d6"
WALLET = "0:eb212ce9fe6df965ebe7202989ef86998739b034c0a87a76487a457eddcbd8c7"
OTHER = "0:9999999999999999999999999999999999999999999999999999999999999999"
SELLER = "0:1111111111111111111111111111111111111111111111111111111111111111"
BUYER = "0:2222222222222222222222222222222222222222222222222222222222222222"

T1 = datetime.fromtimestamp(1753000000, tz=UTC)
T2 = datetime.fromtimestamp(1753003600, tz=UTC)
T3 = datetime.fromtimestamp(1753007200, tz=UTC)


def _load(name: str) -> dict[str, Any]:
    return cast(dict[str, Any], json.loads((FIXTURES / name).read_text(encoding="utf-8")))


def _route_key(path: str) -> str:
    """Свёртка пути TonAPI в короткий ключ роутинга (без составных условий)."""
    if path.startswith("/v2/nfts/"):
        return "nft_history" if path.endswith("/history") else "nft"
    if path.startswith("/v2/accounts/"):
        return "account_events" if path.endswith("/events") else "account"
    return "unknown"


def _route(path: str, params: Any, fixtures: dict[str, Any]) -> tuple[int, dict[str, Any]]:
    """Роутинг MockTransport по путям TonAPI (без else — лимит PLR0912)."""
    segments = [segment for segment in path.split("/") if segment]
    status = 404
    payload: dict[str, Any] = {"error": "not found"}
    key = _route_key(path)
    if key == "nft_history":
        status = 200
        account_id = segments[-2]
        payload = {"events": [], "next_from": 0}
        if account_id != OTHER:
            history = json.loads(json.dumps(fixtures["nft_history"]))
            start_date = int(params.get("start_date") or 0)
            history["events"] = [
                event for event in history["events"] if event["timestamp"] >= start_date
            ]
            payload = history
    elif key == "nft":
        account_id = segments[-1]
        if account_id == NFT:
            status = 200
            payload = fixtures["nft_item"]
    elif key == "account_events":
        status = 200
        account_id = segments[-2]
        payload = fixtures["account_events_window"]
        if account_id != WALLET:
            payload = {"events": [], "next_from": 0}
        elif params.get("sort_order") == "asc":
            payload = fixtures["account_events_first"]
    elif key == "account":
        status = 200
        account_id = segments[-1]
        payload = {"address": account_id, "status": "nonexist", "is_wallet": True}
        if account_id == WALLET:
            payload = fixtures["account"]
    return status, payload


def _transport() -> tuple[httpx.MockTransport, list[httpx.Request]]:
    fixtures = {
        "nft_item": _load("nft_item.json"),
        "nft_history": _load("nft_history.json"),
        "account": _load("account.json"),
        "account_events_first": _load("account_events_first.json"),
        "account_events_window": _load("account_events_window.json"),
    }
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        status, payload = _route(request.url.path, request.url.params, fixtures)
        return httpx.Response(status, json=payload)

    return httpx.MockTransport(handler), captured


def _adapter(
    transport: httpx.AsyncBaseTransport,
    *,
    api_key: str | None = None,
    rate_limiter: Any = None,
    page_size: int = 50,
) -> TonapiChainAdapter:
    http = ResilientHttpClient(client=httpx.AsyncClient(transport=transport), max_retries=0)
    return TonapiChainAdapter(
        http=http,
        endpoint="https://tonapi.io",
        api_key=api_key,
        rate_limiter=rate_limiter,
        page_size=page_size,
    )


class _SpyLimiter:
    def __init__(self) -> None:
        self.calls = 0

    async def acquire(self) -> None:
        self.calls += 1


def make_sale(sale_id: str, item_id: str, price_ton: str, sold_at: datetime) -> SaleEvent:
    return SaleEvent(
        id=sale_id,
        item_id=item_id,
        collection_id="0:coll",
        price=TONAmount.from_ton(Decimal(price_ton)),
        buyer=parse_address(BUYER),
        seller=parse_address(SELLER),
        tx_hash=sale_id,
        sold_at=sold_at,
    )


# ── владелец ────────────────────────────────────────────────────────────


async def test_get_nft_owner_returns_user_friendly() -> None:
    transport, captured = _transport()
    adapter = _adapter(transport)
    owner = await adapter.get_nft_owner(NFT)
    assert owner is not None
    assert owner.startswith("UQ")
    # запрос идёт по raw-адресу
    assert captured[0].url.path == f"/v2/nfts/{NFT}"
    await adapter.aclose()


async def test_get_nft_owner_accepts_user_friendly_input() -> None:
    transport, captured = _transport()
    adapter = _adapter(transport)
    user_friendly = parse_address(NFT).user_friendly()
    owner = await adapter.get_nft_owner(user_friendly)
    assert owner is not None
    assert captured[0].url.path == f"/v2/nfts/{NFT}"
    await adapter.aclose()


async def test_get_nft_owner_not_found_returns_none() -> None:
    transport, _ = _transport()
    adapter = _adapter(transport)
    assert await adapter.get_nft_owner(OTHER) is None
    await adapter.aclose()


# ── трансферы ───────────────────────────────────────────────────────────


async def test_get_nft_transfers_parses_amounts() -> None:
    transport, _ = _transport()
    adapter = _adapter(transport)
    transfers = await adapter.get_nft_transfers(NFT)
    assert [transfer.amount and transfer.amount.formatted for transfer in transfers] == [
        "10",
        "5",
        None,
    ]
    assert transfers[0].from_address == SELLER
    assert transfers[0].to_address == BUYER
    await adapter.aclose()


async def test_get_nft_transfers_since_and_limit() -> None:
    transport, captured = _transport()
    adapter = _adapter(transport)
    transfers = await adapter.get_nft_transfers(NFT, since=T2, limit=1)
    assert len(transfers) == 1
    assert transfers[0].amount == TONAmount.from_ton(5)
    request = captured[0]
    assert int(request.url.params["start_date"]) == int(T2.timestamp())
    await adapter.aclose()


async def test_get_nft_transfers_zero_limit_no_requests() -> None:
    transport, captured = _transport()
    adapter = _adapter(transport)
    assert await adapter.get_nft_transfers(NFT, limit=0) == []
    assert captured == []
    await adapter.aclose()


# ── кошелёк ─────────────────────────────────────────────────────────────


async def test_get_wallet_age_and_inflow() -> None:
    transport, _ = _transport()
    adapter = _adapter(transport)
    wallet = await adapter.get_wallet(WALLET)
    assert wallet is not None
    assert wallet.created_at == datetime.fromtimestamp(1700000000, tz=UTC)
    assert wallet.total_inflow == TONAmount.from_ton(Decimal("1.76"))
    await adapter.aclose()


async def test_get_wallet_nonexist_returns_none() -> None:
    transport, _ = _transport()
    adapter = _adapter(transport)
    assert await adapter.get_wallet(OTHER) is None
    await adapter.aclose()


# ── сверка продаж ───────────────────────────────────────────────────────


async def test_verify_sales_flags_discrepancies() -> None:
    transport, _ = _transport()
    adapter = _adapter(transport)
    sales = [
        make_sale("match", NFT, "10", T1),  # on-chain 10 TON → сходится
        make_sale("mismatch", NFT, "5.2", T2),  # on-chain 5 TON → 4% → флаг
        make_sale("gift", NFT, "1", T3),  # трансфер без суммы → флаг
        make_sale("missing", OTHER, "1", T1),  # нет истории → флаг
    ]
    verifications = await adapter.verify_sales(sales)
    assert [verification.reason for verification in verifications] == [
        None,
        "price_mismatch",
        "no_onchain_amount",
        "transfer_not_found",
    ]
    mismatch = verifications[1]
    assert mismatch.matches is False
    assert mismatch.on_chain_amount == TONAmount.from_ton(5)
    assert mismatch.discrepancy == Decimal("0.04")
    await adapter.aclose()


async def test_verify_sales_caches_history_per_item() -> None:
    transport, captured = _transport()
    adapter = _adapter(transport)
    sales = [make_sale("a", NFT, "10", T1), make_sale("b", NFT, "5", T2)]
    verifications = await adapter.verify_sales(sales)
    assert all(verification.matches for verification in verifications)
    history_requests = [request for request in captured if "/history" in request.url.path]
    assert len(history_requests) == 1  # один запрос истории на предмет
    await adapter.aclose()


async def test_verify_sale_single_convenience() -> None:
    transport, _ = _transport()
    adapter = _adapter(transport)
    assert await adapter.verify_sale(make_sale("match", NFT, "10", T1)) is True
    assert await adapter.verify_sale(make_sale("bad", NFT, "9", T1)) is False
    await adapter.aclose()


# ── транспорт и контракт порта ──────────────────────────────────────────


async def test_auth_header_sent() -> None:
    seen: list[dict[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(dict(request.headers))
        if request.url.path.endswith("/history"):
            return httpx.Response(200, json={"events": [], "next_from": 0})
        return httpx.Response(200, json={"owner": {"address": OWNER}})

    adapter = _adapter(httpx.MockTransport(handler), api_key="secret-key")
    await adapter.get_nft_owner(NFT)
    assert seen[0].get("authorization") == "Bearer secret-key"
    await adapter.aclose()


async def test_rate_limiter_acquired_before_each_request() -> None:
    transport, _ = _transport()
    limiter = _SpyLimiter()
    adapter = _adapter(transport, rate_limiter=limiter)
    await adapter.get_nft_owner(NFT)
    await adapter.get_nft_transfers(NFT)
    assert limiter.calls == 2
    await adapter.aclose()


async def test_unexpected_payload_raises() -> None:
    transport = httpx.MockTransport(lambda req: httpx.Response(200, json=[1, 2, 3]))
    adapter = _adapter(transport)
    with pytest.raises(TonapiResponseError):
        await adapter.get_nft_owner(NFT)
    await adapter.aclose()


def test_adapter_exposes_chain_port_methods() -> None:
    for name in ("get_nft_owner", "get_nft_transfers", "get_wallet", "verify_sale", "verify_sales"):
        assert callable(getattr(TonapiChainAdapter, name))
