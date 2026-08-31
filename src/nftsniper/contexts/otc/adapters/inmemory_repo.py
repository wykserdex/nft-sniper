"""In-memory хранилище сделок (заменится на Postgres, см. ТЗ §5 — alerts/decisions)."""

import asyncio

from nftsniper.contexts.otc.domain.deal import OtcDeal


class InMemoryOtcDealRepository:
    def __init__(self) -> None:
        self._deals: dict[str, OtcDeal] = {}
        self._lock = asyncio.Lock()

    async def add(self, deal: OtcDeal) -> None:
        async with self._lock:
            if deal.id in self._deals:
                msg = f"сделка {deal.id} уже существует"
                raise ValueError(msg)
            self._deals[deal.id] = deal

    async def get(self, deal_id: str) -> OtcDeal | None:
        async with self._lock:
            return self._deals.get(deal_id)

    async def save(self, deal: OtcDeal) -> None:
        async with self._lock:
            self._deals[deal.id] = deal

    async def list_active(self) -> list[OtcDeal]:
        async with self._lock:
            return list(self._deals.values())
