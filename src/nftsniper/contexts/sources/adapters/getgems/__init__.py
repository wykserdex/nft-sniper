"""Адаптер GetGems: реализация MarketplacePort поверх GraphQL.

Нормализация в доменные модели, пагинация, retry — через
infrastructure.http.ResilientHttpClient; rate limit — TokenBucketRateLimiter.
"""

from nftsniper.contexts.sources.adapters.getgems.adapter import GetGemsAdapter
from nftsniper.contexts.sources.adapters.getgems.exceptions import (
    GetGemsError,
    GetGemsGraphQLError,
    GetGemsResponseError,
)
from nftsniper.contexts.sources.adapters.getgems.factory import build_getgems_adapter

__all__ = [
    "GetGemsAdapter",
    "GetGemsError",
    "GetGemsGraphQLError",
    "GetGemsResponseError",
    "build_getgems_adapter",
]
