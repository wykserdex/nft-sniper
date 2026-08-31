"""Фабрика адаптера Fragment из настроек (для bootstrap/workers)."""

from nftsniper.config.settings import Settings
from nftsniper.contexts.sources.adapters.fragment.adapter import FragmentAdapter
from nftsniper.contexts.sources.domain.fragment import FragmentKind
from nftsniper.contexts.sources.ports import ChainPort
from nftsniper.infrastructure.http.client import ResilientHttpClient
from nftsniper.infrastructure.http.ratelimit import TokenBucketRateLimiter


def build_fragment_adapter(settings: Settings, chain: ChainPort) -> FragmentAdapter:
    """Собрать адаптер: on-chain (ChainPort + TonAPI) и scrape fragment.com.

    Реестр коллекций — из настроек: ``fragment_username_collection`` и
    ``fragment_number_collection`` (on-chain адреса коллекций Fragment).
    """
    http = ResilientHttpClient(timeout=settings.fragment_timeout_seconds)
    limiter = TokenBucketRateLimiter(
        rate_per_sec=settings.fragment_rate_limit_rps,
        burst=settings.fragment_rate_limit_burst,
    )
    collections: dict[str, FragmentKind] = {}
    if settings.fragment_username_collection:
        collections[settings.fragment_username_collection] = FragmentKind.USERNAME
    if settings.fragment_number_collection:
        collections[settings.fragment_number_collection] = FragmentKind.NUMBER
    api_key = settings.tonapi_key.get_secret_value() if settings.tonapi_key else None
    return FragmentAdapter(
        chain=chain,
        http=http,
        endpoint=settings.fragment_endpoint,
        tonapi_endpoint=settings.tonapi_endpoint,
        api_key=api_key,
        enabled=settings.fragment_enabled,
        prefer_on_chain=settings.fragment_prefer_on_chain,
        rate_limiter=limiter,
        cache_ttl_seconds=settings.fragment_cache_ttl_seconds,
        page_size=settings.fragment_page_size,
        collections=collections,
    )
