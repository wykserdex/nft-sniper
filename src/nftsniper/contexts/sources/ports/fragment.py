"""Порт Fragment: номера и юзернеймы Telegram.

On-chain — источник истины (существование, имена, владельцы, реальные цены
продаж); парсинг fragment.com — fallback/дополнение для текущих ставок и цен
аукционов (ТЗ §3, §7).
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Protocol

from nftsniper.contexts.sources.domain.fragment import FragmentAsset, FragmentAuction
from nftsniper.contexts.sources.domain.sale import SaleEvent


class FragmentError(RuntimeError):
    """Источник Fragment недоступен или ответил ошибкой.

    Определён на уровне порта, чтобы use cases могли изолировать сбой
    источника, не импортируя конкретный адаптер (ТЗ §7).
    """


class FragmentScrapeError(FragmentError):
    """Сбой обращения к fragment.com (транспорт, не-200, открытый breaker)."""


class FragmentPort(Protocol):
    """Источник данных Fragment (юзернеймы/номера Telegram)."""

    async def get_asset(self, address: str) -> FragmentAsset | None:
        """Актив по on-chain адресу (None, если не существует)."""
        ...

    async def list_assets(
        self,
        collection_address: str,
        limit: int = 100,
    ) -> Sequence[FragmentAsset]:
        """Активы коллекции (on-chain: перечисление + bulk-метаданные)."""
        ...

    async def list_auctions(
        self,
        collection_address: str,
        limit: int = 100,
    ) -> Sequence[FragmentAuction]:
        """Лоты (аукционы/фикс. цены) коллекции; деградирует, а не падает."""
        ...

    async def get_sales(
        self,
        asset_address: str,
        since: datetime | None = None,
        limit: int = 50,
    ) -> Sequence[SaleEvent]:
        """Завершённые продажи актива (on-chain трансферы с суммой)."""
        ...
