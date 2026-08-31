"""ScreenListing: скоринг риска листинга.

``compute_risk`` — чистая функция: прогоняет детекторы по ``ScreeningInput``
и агрегирует ``RiskScore``. ``ScreenListing`` — use case: собирает данные
через порты (каталог коллекций, медиа, chain, продажи) и вызывает
``compute_risk``. Конвейер использует результат до отправки алерта
(ТЗ §4: risk_score <= порога пользователя).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal

from nftsniper.contexts.risk.application.detectors import (
    DEFAULT_CLONE_SIMILARITY,
    DEFAULT_FAKE_SALE_RATIO,
    DEFAULT_FRESH_SELLER_DAYS,
    DEFAULT_LOW_VOLUME_MIN_SALES,
    DEFAULT_ROYALTY_ALERT_RATIO,
    DEFAULT_WASH_MAX_CYCLE,
    DEFAULT_WASH_WINDOW,
    WalletEdge,
    detect_auction_mismatch,
    detect_broken_metadata,
    detect_clone_collection,
    detect_fake_sales,
    detect_low_volume,
    detect_royalty_impact,
    detect_seller_risk,
    detect_wash_trading,
)
from nftsniper.contexts.risk.domain.risk import RiskFlag, RiskScore
from nftsniper.contexts.risk.ports import CollectionCatalogPort, MediaPort
from nftsniper.contexts.sources.application.clock import utcnow
from nftsniper.contexts.sources.domain.chain import WalletInfo
from nftsniper.contexts.sources.domain.collection import Collection
from nftsniper.contexts.sources.domain.listing import Listing
from nftsniper.contexts.sources.domain.sale import SaleEvent
from nftsniper.contexts.sources.ports import ChainPort
from nftsniper.contexts.sources.ports.repositories import SaleRepository

SALES_WINDOW = timedelta(days=30)  # окно для объёма/fake-продаж


@dataclass(frozen=True, slots=True)
class RiskConfig:
    """Пороги детекторов (переопределяются при необходимости)."""

    low_volume_min_sales: int = DEFAULT_LOW_VOLUME_MIN_SALES
    clone_similarity: Decimal = DEFAULT_CLONE_SIMILARITY
    fresh_seller_days: int = DEFAULT_FRESH_SELLER_DAYS
    fake_sale_ratio: Decimal = DEFAULT_FAKE_SALE_RATIO
    wash_window: timedelta = DEFAULT_WASH_WINDOW
    wash_max_cycle_len: int = DEFAULT_WASH_MAX_CYCLE
    royalty_alert_ratio: Decimal = DEFAULT_ROYALTY_ALERT_RATIO
    marketplace_fee_bps: int = 250  # ~2.5% (GetGems)


@dataclass(frozen=True, slots=True)
class ScreeningInput:
    """Всё, что нужно детекторам (собирает use case, без I/O)."""

    listing: Listing
    collection: Collection
    item_sales: tuple[SaleEvent, ...] = ()
    collection_sales_30d: tuple[SaleEvent, ...] = ()
    seller_wallet: WalletInfo | None = None
    media_available: bool | None = None
    is_auction: bool = False
    known_collection_names: tuple[str, ...] = ()


def compute_risk(
    data: ScreeningInput, *, now: datetime, config: RiskConfig | None = None
) -> RiskScore:
    """Прогнать все детекторы и собрать ``RiskScore`` (чистая функция)."""
    cfg = config if config is not None else RiskConfig()
    score = RiskScore.clean()

    flags: list[RiskFlag | None] = [
        detect_clone_collection(
            data.collection.name, data.known_collection_names, similarity=cfg.clone_similarity
        ),
        detect_low_volume(len(data.collection_sales_30d), min_sales=cfg.low_volume_min_sales),
        detect_broken_metadata(data.listing.item.name, media_available=data.media_available),
        detect_seller_risk(data.seller_wallet, now=now, min_age_days=cfg.fresh_seller_days),
        detect_fake_sales(data.collection_sales_30d, ratio=cfg.fake_sale_ratio),
        detect_wash_trading(
            [
                WalletEdge(sale.seller.raw_str, sale.buyer.raw_str, sale.sold_at)
                for sale in data.item_sales
            ],
            now=now,
            window=cfg.wash_window,
            max_cycle_len=cfg.wash_max_cycle_len,
        ),
        detect_auction_mismatch(data.is_auction),
        detect_royalty_impact(
            data.listing.price,
            royalty_bps=data.collection.royalty_bps,
            marketplace_fee_bps=cfg.marketplace_fee_bps,
            alert_ratio=cfg.royalty_alert_ratio,
        ),
    ]
    for flag in flags:
        if flag is not None:
            score = score.with_flag(flag)
    return score


def listing_is_auction(listing: Listing) -> bool:
    """Аукцион ли листинг: смотрим ``sale.endsAt`` в raw (контракт GetGems).

    Фиксированная цена: ``endsAt`` = null; аукцион — не-null (есть дата конца).
    """
    raw = listing.raw or {}
    sale = raw.get("sale")
    if not isinstance(sale, dict):
        return False
    return sale.get("endsAt") is not None


class ScreenListing:
    """Собирает данные через порты и считает риск листинга (ТЗ §7)."""

    def __init__(
        self,
        catalog: CollectionCatalogPort,
        media: MediaPort,
        chain: ChainPort,
        sales: SaleRepository,
        *,
        clock: Callable[[], datetime] = utcnow,
        config: RiskConfig | None = None,
    ) -> None:
        self._catalog = catalog
        self._media = media
        self._chain = chain
        self._sales = sales
        self._clock = clock
        self._config = config

    async def run(
        self,
        listing: Listing,
        *,
        collection: Collection,
    ) -> RiskScore:
        now = self._clock()
        collection_id = listing.item.collection_id
        since = now - SALES_WINDOW

        item_sales = await self._sales.list_by_item(listing.item.id, since)
        collection_sales = await self._sales.list_by_collection(collection_id, since)
        seller_wallet = await self._chain.get_wallet(listing.seller.raw_str)
        known = tuple(await self._catalog.known_collections())
        media_available: bool | None = None
        if listing.item.media_url is not None:
            media_available = await self._media.is_available(listing.item.media_url)

        data = ScreeningInput(
            listing=listing,
            collection=collection,
            item_sales=tuple(item_sales),
            collection_sales_30d=tuple(collection_sales),
            seller_wallet=seller_wallet,
            media_available=media_available,
            is_auction=listing_is_auction(listing),
            known_collection_names=known,
        )
        return compute_risk(data, now=now, config=self._config)
