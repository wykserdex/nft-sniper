"""ResilientHttpClient: retry, backoff, Retry-After, circuit breaker."""

import asyncio
from collections.abc import Callable

import httpx
import pytest

from nftsniper.infrastructure.http.circuit_breaker import (
    CircuitBreaker,
    CircuitBreakerOpenError,
)
from nftsniper.infrastructure.http.client import HttpError, ResilientHttpClient

# Обработчик MockTransport: «ошибка» моделируется исключением из тела функции
Handler = Callable[[httpx.Request], httpx.Response]


def _make_client(
    handler: Handler,
    *,
    max_retries: int = 2,
    breaker: CircuitBreaker | None = None,
) -> ResilientHttpClient:
    transport = httpx.MockTransport(handler)
    client = httpx.AsyncClient(transport=transport)
    effective_breaker = breaker if breaker is not None else CircuitBreaker(failure_threshold=100)
    return ResilientHttpClient(
        client=client,
        max_retries=max_retries,
        backoff_base=0.001,
        breaker=effective_breaker,
    )


async def test_get_json_success() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, json={"price": "120"})

    http = _make_client(handler)
    result = await http.get_json("https://api.example/listings")
    assert result == {"price": "120"}
    assert calls == 1
    await http.aclose()


async def test_retries_on_500_then_succeeds() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(500)
        return httpx.Response(200, json={"ok": True})

    http = _make_client(handler)
    result = await http.get_json("https://api.example/x")
    assert result == {"ok": True}
    assert calls == 2
    await http.aclose()


async def test_429_with_retry_after_is_honoured() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(429, headers={"Retry-After": "0"})
        return httpx.Response(200, json={"ok": True})

    http = _make_client(handler)
    result = await http.get_json("https://api.example/x")
    assert result == {"ok": True}
    assert calls == 2
    await http.aclose()


async def test_no_retry_on_404() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(404)

    http = _make_client(handler)
    with pytest.raises(HttpError) as exc_info:
        await http.get_json("https://api.example/x")
    assert exc_info.value.status_code == 404
    assert calls == 1
    await http.aclose()


async def test_gives_up_after_max_retries() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(503)

    http = _make_client(handler, max_retries=2)
    with pytest.raises(HttpError, match="3 попыток"):
        await http.get_json("https://api.example/x")
    assert calls == 3
    await http.aclose()


async def test_transport_error_retried_then_raised() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("boom")

    http = _make_client(handler, max_retries=1)
    with pytest.raises(HttpError, match="boom"):
        await http.get_json("https://api.example/x")
    await http.aclose()


async def test_non_json_response_raises_http_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="not json")

    http = _make_client(handler)
    with pytest.raises(HttpError, match="не-JSON"):
        await http.get_json("https://api.example/x")
    await http.aclose()


async def test_breaker_opens_after_threshold() -> None:
    breaker = CircuitBreaker(failure_threshold=2, recovery_timeout=60.0)
    http = _make_client(lambda r: httpx.Response(500), max_retries=0, breaker=breaker)

    with pytest.raises(HttpError):
        await http.get_json("https://api.example/x")
    with pytest.raises(HttpError):
        await http.get_json("https://api.example/x")

    assert breaker.state == "open"
    with pytest.raises(CircuitBreakerOpenError):
        await http.get_json("https://api.example/x")
    await http.aclose()


async def test_breaker_half_open_then_closes_on_success() -> None:
    calls = 0
    breaker = CircuitBreaker(failure_threshold=1, recovery_timeout=0.01)

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(500)
        return httpx.Response(200, json={"ok": True})

    http = _make_client(handler, max_retries=0, breaker=breaker)
    with pytest.raises(HttpError):
        await http.get_json("https://api.example/x")
    assert breaker.state == "open"

    await asyncio.sleep(0.02)  # recovery timeout истёк → half_open
    result = await http.get_json("https://api.example/x")
    assert result == {"ok": True}
    assert breaker.state == "closed"
    await http.aclose()


async def test_breaker_reopens_on_half_open_failure() -> None:
    breaker = CircuitBreaker(failure_threshold=1, recovery_timeout=0.01)
    http = _make_client(lambda r: httpx.Response(500), max_retries=0, breaker=breaker)

    with pytest.raises(HttpError):
        await http.get_json("https://api.example/x")
    await asyncio.sleep(0.02)

    with pytest.raises(HttpError):  # half_open-попытка провалилась
        await http.get_json("https://api.example/x")
    assert breaker.state == "open"
    await http.aclose()
