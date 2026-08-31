"""Фабрика адаптера TonAPI из настроек (для bootstrap/workers)."""

from nftsniper.config.settings import Settings
from nftsniper.contexts.sources.adapters.tonapi.adapter import TonapiChainAdapter
from nftsniper.infrastructure.http.client import ResilientHttpClient
from nftsniper.infrastructure.http.ratelimit import TokenBucketRateLimiter


def build_tonapi_adapter(settings: Settings) -> TonapiChainAdapter:
    """Собрать адаптер: HTTP-клиент (retry/breaker), rate limiter, API-ключ."""
    http = ResilientHttpClient(timeout=settings.tonapi_timeout_seconds)
    limiter = TokenBucketRateLimiter(
        rate_per_sec=settings.tonapi_rate_limit_rps,
        burst=settings.tonapi_rate_limit_burst,
    )
    api_key = settings.tonapi_key.get_secret_value() if settings.tonapi_key else None
    return TonapiChainAdapter(
        http=http,
        endpoint=settings.tonapi_endpoint,
        api_key=api_key,
        rate_limiter=limiter,
        page_size=settings.tonapi_transfers_page_size,
        sale_window_seconds=settings.tonapi_sale_window_seconds,
        price_mismatch_tolerance=settings.tonapi_price_mismatch_tolerance,
        wallet_inflow_window=settings.tonapi_wallet_inflow_window,
    )
