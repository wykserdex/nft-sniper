"""Пул Redis (redis.asyncio)."""

import redis.asyncio as aioredis

from nftsniper.config.settings import Settings


def create_redis(settings: Settings) -> aioredis.Redis:
    # redis-py не типизирует from_url (и в 5.x, и в 6.x) — единственный
    # ignore на этой границе; остальной API типизирован.
    return aioredis.from_url(settings.redis_url, decode_responses=True)  # type: ignore[no-untyped-call,no-any-return]


async def ping_redis(pool: aioredis.Redis) -> None:
    """Бросает исключение, если Redis недоступен (для /readyz и `nftsniper check`)."""
    await pool.ping()
