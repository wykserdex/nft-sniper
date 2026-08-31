"""IngestSale: загрузка истории продаж с маркетплейса.

Дедупликация по ``tx_hash`` (уникальный индекс, ТЗ §5) — повторный запуск
идемпотентен. События ``SaleIngested`` кормят statistics/valuation.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from nftsniper.contexts.sources.application.clock import utcnow
from nftsniper.contexts.sources.domain.events import SaleIngested
from nftsniper.contexts.sources.domain.sale import SaleEvent
from nftsniper.contexts.sources.ports import MarketplacePort
from nftsniper.contexts.sources.ports.repositories import SaleRepository


@dataclass(frozen=True, slots=True)
class IngestSaleResult:
    ingested: tuple[SaleEvent, ...]
    events: tuple[SaleIngested, ...]

    @property
    def ingested_count(self) -> int:
        return len(self.ingested)


class IngestSale:
    """Тянет продажи с MarketplacePort с даты ``since`` и сохраняет новые."""

    def __init__(
        self,
        marketplace: MarketplacePort,
        sales: SaleRepository,
        *,
        clock: Callable[[], datetime] = utcnow,
    ) -> None:
        self._marketplace = marketplace
        self._sales = sales
        self._clock = clock

    async def run(
        self,
        collection_address: str,
        since: datetime,
        *,
        limit: int = 500,
        until: datetime | None = None,
    ) -> IngestSaleResult:
        ingested: list[SaleEvent] = []
        events: list[SaleIngested] = []
        for sale in await self._marketplace.get_sales(
            collection_address, since, limit=limit, until=until
        ):
            existing = await self._sales.get(sale.id)
            if existing is not None:
                continue
            await self._sales.add(sale)
            ingested.append(sale)
            events.append(
                SaleIngested(
                    occurred_at=self._clock(),
                    sale_id=sale.id,
                    collection_id=sale.collection_id,
                    item_id=sale.item_id,
                    price=sale.price,
                )
            )
        return IngestSaleResult(ingested=tuple(ingested), events=tuple(events))
