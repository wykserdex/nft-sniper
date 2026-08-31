"""Production-обвязка воркеров: сборка реальных компонентов.

``build_worker(settings)`` собирает конвейер ``poll → score → risk → notify``
на реальных адаптерах (GetGems, TonAPI, Postgres-репозитории, Redis-дедуп)
и возвращает ``WorkerComponents``. Если Telegram-токена нет, нотификатор —
``DevLogNotifier`` (лог вместо отправки), чтобы воркер стартовал без бота.

Каталог коллекций для детектора клонов — имена коллекций из Postgres (все,
что мы уже видели); полный внешний каталог — осознанный MVP-задел.
"""

from __future__ import annotations

import itertools
from dataclasses import dataclass

from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from nftsniper.config.settings import Settings
from nftsniper.contexts.alerts.adapters.telegram.notifier import TelegramNotifier
from nftsniper.contexts.alerts.application.engine import AlertEngine
from nftsniper.contexts.alerts.domain.alert import AlertMessage
from nftsniper.contexts.alerts.ports import AlertRepository
from nftsniper.contexts.risk.adapters.media import HttpMediaChecker
from nftsniper.contexts.risk.application.screen import ScreenListing
from nftsniper.contexts.sources.adapters.getgems.adapter import GetGemsAdapter
from nftsniper.contexts.sources.adapters.tonapi.adapter import TonapiChainAdapter
from nftsniper.contexts.sources.application.poll_listings import PollListings
from nftsniper.contexts.valuation.adapters.ensemble import EnsemblePriceModel
from nftsniper.contexts.valuation.application.estimate_fair_price import (
    EstimateFairPrice,
    ScoreListing,
)
from nftsniper.contexts.valuation.application.rebuild_stats import RebuildStats
from nftsniper.entrypoints.bot.adapters import SubscriberDirectoryFromSettings
from nftsniper.entrypoints.bot.render import render_candidate
from nftsniper.entrypoints.workers.pipeline import ListingPipeline
from nftsniper.infrastructure.cache.alert_store import RedisAlertStore
from nftsniper.infrastructure.cache.redis import create_redis
from nftsniper.infrastructure.database.engine import create_database, create_session_factory
from nftsniper.infrastructure.database.repositories import (
    PostgresAlertRepository,
    PostgresCollectionRepository,
    PostgresFeatureStore,
    PostgresListingRepository,
    PostgresSaleRepository,
    PostgresUserSettingsStore,
    PostgresValuationRepository,
)
from nftsniper.infrastructure.http.client import ResilientHttpClient
from nftsniper.infrastructure.http.ratelimit import TokenBucketRateLimiter
from nftsniper.observability.logging import get_logger

logger = get_logger(__name__)


class DevLogNotifier:
    """NotifierPort без бота: пишет алерт в лог (dev/staging без токена)."""

    def __init__(self) -> None:
        self._ids = itertools.count(1)

    async def send(self, user_id: str, message: AlertMessage) -> str:
        message_id = f"dev-{next(self._ids)}"
        logger.info("alert_logged", user_id=user_id, message_id=message_id, text=message.text)
        return message_id

    async def edit(self, user_id: str, message_id: str, message: AlertMessage) -> None:
        logger.info("alert_edited", user_id=user_id, message_id=message_id)


Notifier = DevLogNotifier | TelegramNotifier


@dataclass(frozen=True, slots=True)
class WorkerComponents:
    """Собранные компоненты воркера (для CLI и тестов wiring)."""

    pipeline: ListingPipeline
    notifier: Notifier


class _CatalogFromRepository:
    """CollectionCatalogPort: имена коллекций из Postgres (что мы уже видели)."""

    def __init__(self, collections: PostgresCollectionRepository) -> None:
        self._collections = collections

    async def known_collections(self) -> list[str]:
        return await self._collections.list_names()


def _build_notifier(settings: Settings) -> Notifier:
    """TelegramNotifier, если есть токен; иначе DevLogNotifier."""
    if settings.telegram_bot_token is None:
        return DevLogNotifier()

    bot = Bot(
        token=settings.telegram_bot_token.get_secret_value(),
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    return TelegramNotifier(bot)


def build_worker(settings: Settings, *, use_redis: bool = True) -> WorkerComponents:
    """Собрать конвейер на реальных адаптерах + Postgres/Redis."""
    engine = create_database(settings)
    sessions = create_session_factory(engine)

    listings = PostgresListingRepository(sessions)
    sales = PostgresSaleRepository(sessions)
    collections = PostgresCollectionRepository(sessions)
    features = PostgresFeatureStore(sessions)
    valuations = PostgresValuationRepository(sessions)

    getgems = GetGemsAdapter(
        http=ResilientHttpClient(timeout=settings.getgems_timeout_seconds),
        endpoint=settings.getgems_endpoint,
        api_key=settings.getgems_api_key.get_secret_value() if settings.getgems_api_key else None,
        rate_limiter=TokenBucketRateLimiter(
            rate_per_sec=settings.getgems_rate_limit_rps,
            burst=settings.getgems_rate_limit_burst,
        ),
        page_size=settings.getgems_page_size,
    )

    chain = TonapiChainAdapter(
        http=ResilientHttpClient(timeout=settings.tonapi_timeout_seconds),
        endpoint=settings.tonapi_endpoint,
        api_key=settings.tonapi_key.get_secret_value() if settings.tonapi_key else None,
        rate_limiter=TokenBucketRateLimiter(
            rate_per_sec=settings.tonapi_rate_limit_rps,
            burst=settings.tonapi_rate_limit_burst,
        ),
        page_size=settings.tonapi_transfers_page_size,
        sale_window_seconds=settings.tonapi_sale_window_seconds,
        price_mismatch_tolerance=settings.tonapi_price_mismatch_tolerance,
        wallet_inflow_window=settings.tonapi_wallet_inflow_window,
    )

    alerts_repo: AlertRepository
    if use_redis:
        alerts_repo = RedisAlertStore(create_redis(settings))
    else:
        alerts_repo = PostgresAlertRepository(sessions)

    media = HttpMediaChecker(ResilientHttpClient(timeout=settings.getgems_timeout_seconds))
    screen = ScreenListing(_CatalogFromRepository(collections), media, chain, sales)

    poller = PollListings(getgems, listings)
    rebuild = RebuildStats(listings, sales, features)
    scorer = ScoreListing(EstimateFairPrice(EnsemblePriceModel(), features, valuations))

    notifier = _build_notifier(settings)
    subscribers = SubscriberDirectoryFromSettings(PostgresUserSettingsStore(sessions))

    alert_engine = AlertEngine(
        notifier=notifier,
        alerts=alerts_repo,
        subscribers=subscribers,
        renderer=render_candidate,
    )

    pipeline = ListingPipeline(
        poller=poller,
        features=features,
        rebuild=rebuild,
        scorer=scorer,
        screen=screen,
        collections=getgems,
        engine=alert_engine,
    )
    return WorkerComponents(pipeline=pipeline, notifier=notifier)
