"""TonAPI Adapter: реализация ChainPort поверх REST v2 TonAPI.

Пайплайн: GET {endpoint}/v2/... → нормализация → доменные модели.

- retry + circuit breaker — через ``ResilientHttpClient`` (infrastructure.http);
- rate limit — ``RateLimiter`` перед каждым запросом;
- авторизация — ``Authorization: Bearer <token>`` (ключ из ``NFT_TONAPI_KEY``);
- ``get_nft_owner`` → ``GET /v2/nfts/{id}`` → ``NftItem.owner``;
- ``get_nft_transfers`` → ``GET /v2/nfts/{id}/history`` → ``AccountEvents``;
- ``get_wallet`` → ``GET /v2/accounts/{id}`` (+ ``/events`` для возраста и
  входящего объёма);
- ``verify_sales`` — сверка цены продажи с on-chain-трансфером; расхождение
  больше ``price_mismatch_tolerance`` (1%, ТЗ §3) помечается флагом
  ``SaleVerification.matches=False``.

Адрес в пути — raw-форма ``0:hex``: пользовательский ввод (``EQ…``/``UQ…``)
приводится через ``TonAddress``. Транспортные ошибки не оборачиваются (их уже
несёт ResilientHttpClient), 404 на NFT трактуется как «предмет не существует».
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from nftsniper.contexts.sources.adapters.tonapi.exceptions import TonapiResponseError
from nftsniper.contexts.sources.adapters.tonapi.normalizer import (
    parse_first_event_timestamp,
    parse_nft_owner,
    parse_transfers,
    parse_wallet,
    sum_inbound_nano,
)
from nftsniper.contexts.sources.domain.chain import (
    NftTransfer,
    SaleVerification,
    WalletInfo,
)
from nftsniper.contexts.sources.domain.sale import SaleEvent
from nftsniper.infrastructure.http.client import HttpError, ResilientHttpClient
from nftsniper.infrastructure.http.ratelimit import RateLimiter
from nftsniper.observability.logging import get_logger
from nftsniper.shared.ton_address import TonAddressError, parse_address

_DEFAULT_TOLERANCE = Decimal("0.01")  # 1% (ТЗ §3)
_DEFAULT_SALE_WINDOW_SECONDS = 300  # ±5 минут вокруг продажи
_HTTP_NOT_FOUND = 404


def _account_id(address: str) -> str:
    """Адрес → raw-форма ``0:hex`` для пути запроса (fallback: как есть)."""
    try:
        return parse_address(address).raw_str
    except (TonAddressError, ValueError):
        return address.strip()


def _as_utc(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


class TonapiChainAdapter:
    """Реализация ``ChainPort`` поверх TonAPI (источник истины, ТЗ §3)."""

    def __init__(
        self,
        *,
        http: ResilientHttpClient,
        endpoint: str = "https://tonapi.io",
        api_key: str | None = None,
        rate_limiter: RateLimiter | None = None,
        page_size: int = 50,
        sale_window_seconds: int = _DEFAULT_SALE_WINDOW_SECONDS,
        price_mismatch_tolerance: Decimal = _DEFAULT_TOLERANCE,
        wallet_inflow_window: int = 100,
    ) -> None:
        self._http = http
        self._endpoint = endpoint.rstrip("/")
        self._api_key = api_key
        self._limiter = rate_limiter
        self._page_size = page_size
        self._sale_window = timedelta(seconds=sale_window_seconds)
        self._tolerance = price_mismatch_tolerance
        self._inflow_window = wallet_inflow_window
        self._log = get_logger(__name__, source="tonapi")

    async def get_nft_owner(self, address: str) -> str | None:
        account_id = _account_id(address)
        try:
            data = await self._get(f"/v2/nfts/{account_id}")
        except HttpError as exc:
            if exc.status_code == _HTTP_NOT_FOUND:
                return None
            raise
        if not isinstance(data, dict):
            msg = f"TonAPI get_nft_owner: ожидался JSON-объект, получено {type(data).__name__}"
            raise TonapiResponseError(msg)
        return parse_nft_owner(data)

    async def get_nft_transfers(
        self,
        address: str,
        since: datetime | None = None,
        limit: int = 50,
    ) -> Sequence[NftTransfer]:
        if limit <= 0:
            return []
        account_id = _account_id(address)
        params: dict[str, Any] = {"limit": min(limit, self._page_size)}
        if since is not None:
            params["start_date"] = int(_as_utc(since).timestamp())
        data = await self._get(f"/v2/nfts/{account_id}/history", params=params)
        if not isinstance(data, dict):
            msg = f"TonAPI get_nft_transfers: ожидался JSON-объект, получено {type(data).__name__}"
            raise TonapiResponseError(msg)
        transfers = parse_transfers(data.get("events"), nft_address=account_id)
        return transfers[:limit]

    async def get_wallet(self, address: str) -> WalletInfo | None:
        account_id = _account_id(address)
        account = await self._get(f"/v2/accounts/{account_id}")
        if not isinstance(account, dict):
            msg = f"TonAPI get_wallet: ожидался JSON-объект, получено {type(account).__name__}"
            raise TonapiResponseError(msg)
        if account.get("status") == "nonexist":
            return None

        first = await self._get(
            f"/v2/accounts/{account_id}/events",
            params={"limit": 1, "sort_order": "asc"},
        )
        first_ts = parse_first_event_timestamp(first)

        recent = await self._get(
            f"/v2/accounts/{account_id}/events",
            params={"limit": self._inflow_window},
        )
        inflow = sum_inbound_nano(recent, wallet_address=account_id)
        return parse_wallet(account, first_event_timestamp=first_ts, total_inflow_nano=inflow)

    async def verify_sale(self, sale: SaleEvent) -> bool:
        verified = await self.verify_sales([sale])
        return verified[0].matches

    async def verify_sales(self, sales: Sequence[SaleEvent]) -> Sequence[SaleVerification]:
        """Сверка выборки продаж с on-chain (ТЗ §3).

        Для каждого предмета история трансферов запрашивается один раз
        (кэш по item_id) — продажи одного предмета не плодят запросы.
        """
        results: list[SaleVerification] = []
        cache: dict[str, list[NftTransfer]] = {}
        for sale in sales:
            transfers = cache.get(sale.item_id)
            if transfers is None:
                since = _as_utc(sale.sold_at) - self._sale_window
                transfers = list(
                    await self.get_nft_transfers(sale.item_id, since=since, limit=self._page_size)
                )
                cache[sale.item_id] = transfers
            results.append(self._verify_one(sale, transfers))
        return results

    async def aclose(self) -> None:
        await self._http.aclose()

    # ── внутренние ──────────────────────────────────────────────────────

    def _verify_one(self, sale: SaleEvent, transfers: Sequence[NftTransfer]) -> SaleVerification:
        sold_at = _as_utc(sale.sold_at)
        window_start = sold_at - self._sale_window
        window_end = sold_at + self._sale_window
        candidates = [
            transfer for transfer in transfers if window_start <= transfer.timestamp <= window_end
        ]
        with_amount = [transfer for transfer in candidates if transfer.amount is not None]
        if not with_amount:
            reason = "no_onchain_amount" if candidates else "transfer_not_found"
            return SaleVerification(
                sale_id=sale.id,
                marketplace_amount=sale.price,
                matches=False,
                reason=reason,
            )
        best = min(with_amount, key=lambda t: abs((t.timestamp - sold_at).total_seconds()))
        on_chain = best.amount
        assert on_chain is not None  # гарантировано фильтром with_amount
        if on_chain.is_zero:
            return SaleVerification(
                sale_id=sale.id,
                marketplace_amount=sale.price,
                on_chain_amount=on_chain,
                matches=False,
                reason="zero_onchain_amount",
            )
        discrepancy = abs(on_chain.ton - sale.price.ton) / on_chain.ton
        matches = discrepancy <= self._tolerance
        return SaleVerification(
            sale_id=sale.id,
            marketplace_amount=sale.price,
            on_chain_amount=on_chain,
            discrepancy=discrepancy,
            matches=matches,
            reason=None if matches else "price_mismatch",
        )

    async def _get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        if self._limiter is not None:
            await self._limiter.acquire()
        headers: dict[str, str] = {}
        if self._api_key is not None:
            headers["Authorization"] = f"Bearer {self._api_key}"
        return await self._http.get_json(f"{self._endpoint}{path}", params=params, headers=headers)
