"""Общий HTTP-клиент: retry с экспоненциальным backoff + circuit breaker.

Через него идут все внешние адаптеры (GetGems, TonAPI, TonCenter, Fragment,
CoinGecko). Повторяются: транспортные ошибки и статусы 429/5xx.
Не повторяются: 4xx (кроме 429) — повторять бессмысленно.
``Retry-After`` на 429 уважается.
"""

import asyncio
import random
from typing import Any

import httpx

from nftsniper.infrastructure.http.circuit_breaker import (
    CircuitBreaker,
    CircuitBreakerOpenError,
)

RETRYABLE_STATUS = frozenset({429, 500, 502, 503, 504})
_MAX_BACKOFF_SECONDS = 30.0
_CLIENT_ERROR_MIN_STATUS = 400
_METHOD_NOT_ALLOWED = 405
_NOT_IMPLEMENTED = 501


class HttpError(RuntimeError):
    """Сетевой запрос не удался либо пришёл не-JSON ответ."""

    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class _RetryableResponse(Exception):
    """Внутренний маркер: ответ с 429/5xx, допустимо повторить."""

    def __init__(self, retry_after: str | None, status_code: int) -> None:
        super().__init__(f"HTTP {status_code}")
        self.retry_after = _parse_retry_after(retry_after)


def _parse_retry_after(value: str | None) -> float | None:
    """Понимает только целые секунды; HTTP-дата — просто игнорируется."""
    if value is None:
        return None
    try:
        return float(value)
    except ValueError:
        return None


class ResilientHttpClient:
    """Асинхронная обёртка над httpx с retry и circuit breaker."""

    def __init__(
        self,
        *,
        timeout: float = 10.0,
        max_retries: int = 3,
        backoff_base: float = 0.5,
        breaker: CircuitBreaker | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._max_retries = max_retries
        self._backoff_base = backoff_base
        self._breaker = breaker if breaker is not None else CircuitBreaker()
        self._client = client if client is not None else httpx.AsyncClient(timeout=timeout)

    async def aclose(self) -> None:
        await self._client.aclose()

    async def get_json(self, url: str, **kwargs: Any) -> Any:
        response = await self._request("GET", url, **kwargs)
        try:
            return response.json()
        except ValueError as exc:
            raise HttpError(f"не-JSON ответ от {url}") from exc

    async def post_json(self, url: str, *, json: Any | None = None, **kwargs: Any) -> Any:
        response = await self._request("POST", url, json=json, **kwargs)
        try:
            return response.json()
        except ValueError as exc:
            raise HttpError(f"не-JSON ответ от {url}") from exc

    async def get_text(self, url: str, **kwargs: Any) -> str:
        response = await self._request("GET", url, **kwargs)
        return response.text

    async def is_reachable(self, url: str, **kwargs: Any) -> bool:
        """HEAD-запрос: True, если ресурс доступен (2xx/3xx).

        405/501 (HEAD не поддержан сервером) трактуются как «ресурс есть».
        Транспортные ошибки, 4xx/5xx и открытый breaker → False. Используется
        risk-проверкой доступности медиа.
        """
        try:
            await self._request("HEAD", url, **kwargs)
        except HttpError as exc:
            return exc.status_code in (_METHOD_NOT_ALLOWED, _NOT_IMPLEMENTED)
        except CircuitBreakerOpenError:
            return False
        return True

    async def _request(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        async def attempt() -> httpx.Response:
            response = await self._client.request(method, url, **kwargs)
            if response.status_code in RETRYABLE_STATUS:
                raise _RetryableResponse(response.headers.get("Retry-After"), response.status_code)
            if response.status_code >= _CLIENT_ERROR_MIN_STATUS:
                raise HttpError(
                    f"HTTP {response.status_code} для {url}",
                    status_code=response.status_code,
                )
            return response

        last_error: Exception | None = None
        for try_number in range(self._max_retries + 1):
            try:
                return await self._breaker.call(attempt)
            except CircuitBreakerOpenError:
                raise
            except (httpx.TransportError, _RetryableResponse) as exc:
                last_error = exc
                if try_number < self._max_retries:
                    retry_after = exc.retry_after if isinstance(exc, _RetryableResponse) else None
                    await self._sleep_backoff(try_number, retry_after)
        raise HttpError(
            f"запрос к {url} не удался после {self._max_retries + 1} попыток: {last_error}"
        ) from last_error

    async def _sleep_backoff(self, attempt: int, retry_after: float | None) -> None:
        if retry_after is not None:
            delay = min(retry_after, _MAX_BACKOFF_SECONDS)
        else:
            delay = min(self._backoff_base * (2**attempt), _MAX_BACKOFF_SECONDS)
        jitter = random.uniform(0.0, delay * 0.1)
        await asyncio.sleep(delay + jitter)
