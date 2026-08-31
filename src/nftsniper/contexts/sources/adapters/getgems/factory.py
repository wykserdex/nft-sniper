"""Фабрика адаптера GetGems из настроек (для bootstrap/workers)."""

from nftsniper.config.settings import Settings
from nftsniper.contexts.sources.adapters.getgems.adapter import GetGemsAdapter
from nftsniper.infrastructure.http.client import ResilientHttpClient
from nftsniper.infrastructure.http.ratelimit import TokenBucketRateLimiter


def build_getgems_adapter(settings: Settings) -> GetGemsAdapter:
    """Собрать адаптер: HTTP-клиент (retry/breaker), rate limiter, API-ключ."""
    http = ResilientHttpClient(timeout=settings.getgems_timeout_seconds)
    limiter = TokenBucketRateLimiter(
        rate_per_sec=settings.getgems_rate_limit_rps,
        burst=settings.getgems_rate_limit_burst,
    )
    api_key = settings.getgems_api_key.get_secret_value() if settings.getgems_api_key else None
    return GetGemsAdapter(
        http=http,
        endpoint=settings.getgems_endpoint,
        api_key=api_key,
        rate_limiter=limiter,
        page_size=settings.getgems_page_size,
    )
