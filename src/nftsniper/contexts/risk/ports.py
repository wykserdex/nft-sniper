"""Порты контекста risk.

Скринеру нужны два внешних факта, которые нельзя вычислить из доменных
значений: каталог известных коллекций (детектор клонов) и доступность медиа
по URL (детектор битых метаданных). Оба за портами — адаптеры заменяемы.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol


class CollectionCatalogPort(Protocol):
    """Каталог известных коллекций для детектора клонов/подмен (ТЗ §4)."""

    async def known_collections(self) -> Sequence[str]:
        """Имена известных коллекций (включая сами проверяемые)."""
        ...


class MediaPort(Protocol):
    """Проверка доступности медиа (IPFS/CDN) по URL (ТЗ §4)."""

    async def is_available(self, url: str) -> bool:
        """True, если медиа отвечает 2xx/3xx; False на 4xx/5xx/ошибке."""
        ...
