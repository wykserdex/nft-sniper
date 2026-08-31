"""Медиа-проверка: адаптер MediaPort поверх ResilientHttpClient.

HEAD-запрос к URL медиа (IPFS/CDN). Транспортные ошибки и 4xx/5xx → False
(медиа недоступно), открытый breaker → False; 405/501 (HEAD не поддержан)
трактуются как «ресурс есть» (метод не поддержан, но сервер ответил).
"""

from __future__ import annotations

from nftsniper.infrastructure.http.client import ResilientHttpClient


class HttpMediaChecker:
    """Реализация ``MediaPort``: доступность медиа по URL."""

    def __init__(self, http: ResilientHttpClient) -> None:
        self._http = http

    async def is_available(self, url: str) -> bool:
        return await self._http.is_reachable(url)
