"""BackfillHistory: загрузка истории продаж коллекции окнами.

Продажи маркетплейс отдаёт newest-first и лимитированно, поэтому глубокая
история грузится окнами: верхняя граница окна (``until``) сдвигается к самой
старой продаже предыдущего окна, пока окно не станет неполным (история
исчерпана) или не случится дубль без прогресса (защита от зацикливания).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from nftsniper.contexts.sources.application.clock import utcnow
from nftsniper.contexts.sources.application.ingest_sale import IngestSale

_MAX_WINDOWS = 40


@dataclass(frozen=True, slots=True)
class BackfillResult:
    since: datetime
    ingested: int
    windows: int

    @property
    def ingested_count(self) -> int:
        return self.ingested


class BackfillHistory:
    """Заполняет историю продаж коллекции от ``since`` до настоящего момента.

    Каждое окно — IngestSale (дедуп по tx_hash), поэтому повторный запуск
    идемпотентен.
    """

    def __init__(
        self,
        ingest: IngestSale,
        *,
        max_windows: int = _MAX_WINDOWS,
        clock: Callable[[], datetime] = utcnow,
    ) -> None:
        self._ingest = ingest
        self._max_windows = max_windows
        self._clock = clock

    async def run(
        self,
        collection_address: str,
        since: datetime,
        *,
        limit: int = 500,
    ) -> BackfillResult:
        since_utc = since if since.tzinfo is not None else since.replace(tzinfo=UTC)
        until = self._clock()
        total = 0
        windows = 0
        while windows < self._max_windows:
            result = await self._ingest.run(collection_address, since_utc, limit=limit, until=until)
            windows += 1
            total += result.ingested_count
            if result.ingested_count < limit:
                break  # окно неполное — история исчерпана
            oldest = min(sale.sold_at for sale in result.ingested)
            if oldest <= since_utc:
                break  # прогресса нет — дошли до нижней границы
            until = oldest - timedelta(microseconds=1)
        return BackfillResult(since=since_utc, ingested=total, windows=windows)
