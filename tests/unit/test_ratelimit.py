"""TokenBucketRateLimiter: бурст мгновенный, сверх бурста — троттлинг."""

import time
from decimal import Decimal

import pytest

from nftsniper.infrastructure.http.ratelimit import TokenBucketRateLimiter


async def test_burst_is_immediate() -> None:
    limiter = TokenBucketRateLimiter(rate_per_sec=Decimal("1000"), burst=Decimal("3"))
    start = time.monotonic()
    for _ in range(3):
        await limiter.acquire()
    assert time.monotonic() - start < 0.05


async def test_rate_is_enforced_beyond_burst() -> None:
    # 100 токенов/с, бурст 1: 5 запросов = 4 интервала по ~10 мс
    limiter = TokenBucketRateLimiter(rate_per_sec=Decimal("100"), burst=Decimal("1"))
    start = time.monotonic()
    for _ in range(5):
        await limiter.acquire()
    elapsed = time.monotonic() - start
    assert elapsed >= 0.03, f"ожидался троттлинг, прошло {elapsed:.4f} c"
    assert elapsed < 1.0


def test_zero_rate_rejected() -> None:
    with pytest.raises(ValueError, match="положительным"):
        TokenBucketRateLimiter(rate_per_sec=Decimal("0"))


def test_negative_rate_rejected() -> None:
    with pytest.raises(ValueError, match="положительным"):
        TokenBucketRateLimiter(rate_per_sec=Decimal("-1"))


def test_rate_property() -> None:
    limiter = TokenBucketRateLimiter(rate_per_sec=Decimal("7.5"))
    assert limiter.rate_per_sec == 7.5
