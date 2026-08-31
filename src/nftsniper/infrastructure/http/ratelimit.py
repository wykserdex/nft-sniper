"""Асинхронный token bucket для ограничения частоты запросов к внешним API.

Нужен каждому адаптеру источников (GetGems, TonAPI, Fragment): «ограничить
частоту» — требование ТЗ §3 и §7. Модуль живёт в infrastructure/http, потому
что оперирует секундами (float допустим только в этом каталоге, см.
scripts/no_float.py); наружу принимает Decimal и int, чтобы бизнес-код не
трогал float.

Алгоритм: бакет ёмкостью ``burst`` пополняется со скоростью ``rate_per_sec``
токенов в секунду. ``acquire()`` не выбрасывает ошибок — конвейер просто
замедляется под лимитом, а не падает.
"""

from __future__ import annotations

import asyncio
import time
from decimal import Decimal
from typing import Protocol

_MAX_SLEEP_SECONDS = 60.0


class RateLimiter(Protocol):
    """Ограничитель частоты: ``acquire()`` ждёт, пока запрос можно отправить."""

    async def acquire(self) -> None: ...


class TokenBucketRateLimiter:
    """Token bucket: пополнение rate_per_sec токенов/с, ёмкость burst.

    ``burst`` по умолчанию равен ``rate_per_sec`` (т.е. стартовый бурст
    в одну секунду). Безопасен при конкурентном использовании (asyncio.Lock).
    """

    def __init__(self, *, rate_per_sec: Decimal, burst: Decimal | None = None) -> None:
        rate = float(rate_per_sec)
        if rate <= 0:
            msg = "rate_per_sec должен быть положительным"
            raise ValueError(msg)
        capacity = float(burst) if burst is not None else rate
        if capacity < 1:
            capacity = 1.0
        self._rate = rate
        self._capacity = capacity
        self._tokens = capacity
        self._updated = time.monotonic()
        self._lock = asyncio.Lock()

    @property
    def rate_per_sec(self) -> float:
        return self._rate

    async def acquire(self) -> None:
        """Дождаться свободного токена перед запросом."""
        while True:
            async with self._lock:
                self._refill()
                if self._tokens >= 1.0:
                    self._tokens -= 1.0
                    return
                wait = (1.0 - self._tokens) / self._rate
            await asyncio.sleep(min(wait, _MAX_SLEEP_SECONDS))

    def _refill(self) -> None:
        now = time.monotonic()
        elapsed = now - self._updated
        self._tokens = min(self._capacity, self._tokens + elapsed * self._rate)
        self._updated = now
