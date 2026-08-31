"""Postgres-репозитории: реализация портов на SQLAlchemy 2.0 async.

Каждый репозиторий принимает ``async_sessionmaker`` и конвертирует доменные
объекты в ORM-модели и обратно. Деньги — nanoTON (int), адреса — ``raw_str``,
Decimal — Numeric; JSON-поля (трейты, история floor, тихие часы) сериализуют
Decimal через строку (JSON не умеет Decimal, float запрещён).

Заменяют in-memory fake'и из ``entrypoints/bot/adapters.py`` и ``tests/fakes.py``
в проде; интерфейсы совпадают, поэтому use cases не меняются.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nftsniper.contexts.alerts.domain.alert import Alert, Decision
from nftsniper.contexts.alerts.domain.outcome import Outcome
from nftsniper.contexts.sources.domain.collection import Collection
from nftsniper.contexts.sources.domain.item import Item, Trait, TraitSet
from nftsniper.contexts.sources.domain.listing import Listing, ListingStatus
from nftsniper.contexts.sources.domain.marketplace import Marketplace
from nftsniper.contexts.sources.domain.sale import SaleEvent
from nftsniper.contexts.valuation.domain.fair_price import (
    CollectionFeatures,
    EstimationMethod,
    FairPriceEstimate,
)
from nftsniper.entrypoints.bot.domain import UserSettings
from nftsniper.infrastructure.database.models import (
    AlertModel,
    AlertRegistryModel,
    CollectionModel,
    DecisionModel,
    ItemModel,
    ListingModel,
    OutcomeModel,
    PriceStatsModel,
    SaleModel,
    UserSettingsModel,
    ValuationModel,
    WatchlistModel,
)
from nftsniper.shared.money import TONAmount
from nftsniper.shared.ton_address import TonAddress

# ── конвертация домен ↔ модель ──────────────────────────────────────────


def _marketplace(value: str | None) -> Marketplace | None:
    return Marketplace(value) if value is not None else None


def _status(value: str) -> ListingStatus:
    return ListingStatus(value)


def _traits_to_json(traits: TraitSet) -> list[dict[str, object]]:
    return [
        {
            "name": trait.name,
            "value": trait.value,
            "rarity": None if trait.rarity is None else str(trait.rarity),
        }
        for trait in traits
    ]


def _traits_from_json(payload: object) -> TraitSet:
    if not isinstance(payload, list):
        return TraitSet(traits=())
    traits: list[Trait] = []
    for entry in payload:
        if not isinstance(entry, dict):
            continue
        name = entry.get("name")
        value = entry.get("value")
        if not isinstance(name, str) or not isinstance(value, str):
            continue
        rarity_raw = entry.get("rarity")
        rarity = Decimal(rarity_raw) if isinstance(rarity_raw, str) else None
        traits.append(Trait(name=name, value=value, rarity=rarity))
    return TraitSet(traits=tuple(traits))


def _decimals_to_json(values: Sequence[Decimal]) -> list[str]:
    return [str(value) for value in values]


def _decimals_from_json(payload: object) -> tuple[Decimal, ...]:
    if not isinstance(payload, list):
        return ()
    return tuple(Decimal(value) for value in payload if isinstance(value, str))


def _quiet_hours_to_json(hours: Sequence[tuple[int, int]]) -> list[list[int]]:
    return [[start, end] for start, end in hours]


def _quiet_hours_from_json(payload: object) -> tuple[tuple[int, int], ...]:
    if not isinstance(payload, list):
        return ()
    result: list[tuple[int, int]] = []
    for entry in payload:
        if isinstance(entry, list) and len(entry) == 2:  # noqa: PLR2004
            result.append((int(entry[0]), int(entry[1])))
    return tuple(result)


def _strings_from_json(payload: object) -> tuple[str, ...]:
    if not isinstance(payload, list):
        return ()
    return tuple(str(value) for value in payload if isinstance(value, str))


def _item_to_model(item: Item) -> ItemModel:
    return ItemModel(
        id=item.id,
        collection_id=item.collection_id,
        index=item.index,
        name=item.name,
        traits=_traits_to_json(item.traits),
        rarity_rank=item.rarity_rank,
        rarity_score=item.rarity_score,
        media_url=item.media_url,
    )


def _item_from_model(model: ItemModel) -> Item:
    return Item(
        id=model.id,
        collection_id=model.collection_id,
        index=model.index,
        name=model.name,
        traits=_traits_from_json(model.traits),
        rarity_rank=model.rarity_rank,
        rarity_score=model.rarity_score,
        media_url=model.media_url,
    )


def _listing_to_model(listing: Listing) -> ListingModel:
    return ListingModel(
        id=listing.id,
        external_id=listing.external_id,
        marketplace=listing.marketplace.value,
        item_id=listing.item.id,
        price_nano=listing.price.nano,
        currency=listing.currency,
        seller=listing.seller.raw_str,
        listed_at=listing.listed_at,
        closed_at=listing.closed_at,
        status=listing.status.value,
        raw=listing.raw,
    )


def _listing_from_model(model: ListingModel, item: Item) -> Listing:
    return Listing(
        id=model.id,
        external_id=model.external_id,
        marketplace=Marketplace(model.marketplace),
        item=item,
        price=TONAmount.from_nano(model.price_nano),
        seller=TonAddress.from_raw(model.seller),
        currency=model.currency,
        listed_at=model.listed_at,
        closed_at=model.closed_at,
        status=_status(model.status),
        raw=model.raw,
    )


def _sale_to_model(sale: SaleEvent) -> SaleModel:
    return SaleModel(
        id=sale.id,
        item_id=sale.item_id,
        collection_id=sale.collection_id,
        price_nano=sale.price.nano,
        buyer=sale.buyer.raw_str,
        seller=sale.seller.raw_str,
        tx_hash=sale.tx_hash,
        sold_at=sale.sold_at,
        marketplace=sale.marketplace.value if sale.marketplace is not None else None,
        is_suspicious=sale.is_suspicious,
    )


def _sale_from_model(model: SaleModel) -> SaleEvent:
    return SaleEvent(
        id=model.id,
        item_id=model.item_id,
        collection_id=model.collection_id,
        price=TONAmount.from_nano(model.price_nano),
        buyer=TonAddress.from_raw(model.buyer),
        seller=TonAddress.from_raw(model.seller),
        tx_hash=model.tx_hash,
        sold_at=model.sold_at,
        marketplace=_marketplace(model.marketplace),
        is_suspicious=model.is_suspicious,
    )


def _collection_to_model(collection: Collection) -> CollectionModel:
    return CollectionModel(
        id=collection.id,
        name=collection.name,
        slug=collection.slug,
        marketplace=collection.marketplace.value if collection.marketplace is not None else None,
        verified=collection.verified,
        created_at=collection.created_at,
        items_count=collection.items_count,
        royalty_bps=collection.royalty_bps,
        risk_score=collection.risk_score,
    )


def _collection_from_model(model: CollectionModel) -> Collection:
    return Collection(
        id=model.id,
        name=model.name,
        slug=model.slug,
        marketplace=_marketplace(model.marketplace),
        verified=model.verified,
        created_at=model.created_at,
        items_count=model.items_count,
        royalty_bps=model.royalty_bps,
        risk_score=model.risk_score,
    )


def _features_to_model(features: CollectionFeatures) -> PriceStatsModel:
    return PriceStatsModel(
        collection_id=features.collection_id,
        floor_p5_nano=features.floor_p5.nano,
        median_7d_nano=features.median_7d.nano,
        volume_24h_nano=features.volume_24h.nano,
        sales_per_day=features.sales_per_day,
        sales_7d=features.sales_7d,
        listings_count=features.listings_count,
        floor_24h_change=features.floor_24h_change,
        floor_7d_change=features.floor_7d_change,
        as_of=features.as_of,
        floor_history=_decimals_to_json(features.floor_history),
    )


def _features_from_model(model: PriceStatsModel) -> CollectionFeatures:
    return CollectionFeatures(
        collection_id=model.collection_id,
        floor_p5=TONAmount.from_nano(model.floor_p5_nano),
        median_7d=TONAmount.from_nano(model.median_7d_nano),
        volume_24h=TONAmount.from_nano(model.volume_24h_nano),
        sales_per_day=model.sales_per_day,
        sales_7d=model.sales_7d,
        listings_count=model.listings_count,
        floor_24h_change=model.floor_24h_change,
        floor_7d_change=model.floor_7d_change,
        as_of=model.as_of,
        floor_history=_decimals_from_json(model.floor_history),
    )


def _estimate_to_model(listing_id: str, estimate: FairPriceEstimate) -> ValuationModel:
    return ValuationModel(
        id=uuid.uuid4().hex,
        listing_id=listing_id,
        fair_price_nano=estimate.value.nano,
        confidence=estimate.confidence,
        method=estimate.method.value,
        lower_bound_nano=estimate.lower_bound.nano,
        upper_bound_nano=estimate.upper_bound.nano,
        sample_size=estimate.sample_size,
        explanation=list(estimate.explanation),
        model_version=estimate.model_version,
        created_at=datetime.now().astimezone(),
    )


def _estimate_from_model(model: ValuationModel) -> FairPriceEstimate:
    return FairPriceEstimate(
        value=TONAmount.from_nano(model.fair_price_nano),
        confidence=model.confidence,
        method=EstimationMethod(model.method),
        lower_bound=TONAmount.from_nano(model.lower_bound_nano),
        upper_bound=TONAmount.from_nano(model.upper_bound_nano),
        sample_size=model.sample_size,
        explanation=tuple(str(part) for part in model.explanation),
        model_version=model.model_version,
    )


def _alert_to_model(alert: Alert) -> AlertModel:
    return AlertModel(
        id=alert.id,
        user_id=alert.user_id,
        listing_id=alert.listing_id,
        valuation_id=alert.valuation_id,
        dedup_key=alert.dedup_key,
        sent_at=alert.sent_at,
        message_id=alert.message_id,
    )


def _alert_from_model(model: AlertModel) -> Alert:
    return Alert(
        id=model.id,
        user_id=model.user_id,
        listing_id=model.listing_id,
        valuation_id=model.valuation_id,
        dedup_key=model.dedup_key,
        sent_at=model.sent_at,
        message_id=model.message_id,
    )


def _outcome_to_model(outcome: Outcome) -> OutcomeModel:
    return OutcomeModel(
        id=outcome.id,
        alert_id=outcome.alert_id,
        user_id=outcome.user_id,
        listing_id=outcome.listing_id,
        alert_price_nano=outcome.alert_price.nano,
        fair_price_nano=outcome.fair_price.nano,
        discount=outcome.discount,
        price_after_1h_nano=None if outcome.price_after_1h is None else outcome.price_after_1h.nano,
        price_after_24h_nano=None
        if outcome.price_after_24h is None
        else outcome.price_after_24h.nano,
        price_after_7d_nano=None if outcome.price_after_7d is None else outcome.price_after_7d.nano,
        sold_at=outcome.sold_at,
        sold_price_nano=None if outcome.sold_price is None else outcome.sold_price.nano,
        computed_at=outcome.computed_at,
    )


def _outcome_from_model(model: OutcomeModel) -> Outcome:
    return Outcome(
        id=model.id,
        alert_id=model.alert_id,
        user_id=model.user_id,
        listing_id=model.listing_id,
        alert_price=TONAmount.from_nano(model.alert_price_nano),
        fair_price=TONAmount.from_nano(model.fair_price_nano),
        discount=model.discount,
        price_after_1h=None
        if model.price_after_1h_nano is None
        else TONAmount.from_nano(model.price_after_1h_nano),
        price_after_24h=None
        if model.price_after_24h_nano is None
        else TONAmount.from_nano(model.price_after_24h_nano),
        price_after_7d=None
        if model.price_after_7d_nano is None
        else TONAmount.from_nano(model.price_after_7d_nano),
        sold_at=model.sold_at,
        sold_price=None
        if model.sold_price_nano is None
        else TONAmount.from_nano(model.sold_price_nano),
        computed_at=model.computed_at,
    )


# ── репозитории sources ─────────────────────────────────────────────────


class PostgresListingRepository:
    """ListingRepository: upsert по (marketplace, external_id) — идемпотентность."""

    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def save(self, listing: Listing) -> None:
        async with self._sessions() as session:
            await session.merge(_item_to_model(listing.item))
            await session.merge(_listing_to_model(listing))
            await session.commit()

    async def _load_item(self, session: AsyncSession, item_id: str) -> Item | None:
        model = await session.get(ItemModel, item_id)
        return None if model is None else _item_from_model(model)

    async def get(self, listing_id: str) -> Listing | None:
        async with self._sessions() as session:
            model = await session.get(ListingModel, listing_id)
            if model is None:
                return None
            item = await self._load_item(session, model.item_id)
            if item is None:
                return None
            return _listing_from_model(model, item)

    async def get_by_dedup_key(self, dedup_key: str) -> Listing | None:
        marketplace, _, external_id = dedup_key.partition(":")
        async with self._sessions() as session:
            result = await session.execute(
                select(ListingModel).where(
                    ListingModel.marketplace == marketplace,
                    ListingModel.external_id == external_id,
                )
            )
            model = result.scalars().first()
            if model is None:
                return None
            item = await self._load_item(session, model.item_id)
            if item is None:
                return None
            return _listing_from_model(model, item)

    async def list_active(
        self, collection_id: str | None = None, limit: int = 200
    ) -> Sequence[Listing]:
        async with self._sessions() as session:
            stmt = (
                select(ListingModel, ItemModel)
                .join(ItemModel, ListingModel.item_id == ItemModel.id)
                .where(ListingModel.status == ListingStatus.ACTIVE.value)
            )
            if collection_id is not None:
                stmt = stmt.where(ItemModel.collection_id == collection_id)
            rows = (await session.execute(stmt.limit(limit))).all()
            return [
                _listing_from_model(listing_model, _item_from_model(item_model))
                for listing_model, item_model in rows
            ]


class PostgresSaleRepository:
    """SaleRepository: история продаж по предмету/коллекции с окнами."""

    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def get(self, sale_id: str) -> SaleEvent | None:
        async with self._sessions() as session:
            model = await session.get(SaleModel, sale_id)
            return None if model is None else _sale_from_model(model)

    async def add(self, sale: SaleEvent) -> None:
        async with self._sessions() as session:
            await session.merge(_sale_to_model(sale))
            await session.commit()

    async def list_by_item(self, item_id: str, since: datetime) -> Sequence[SaleEvent]:
        async with self._sessions() as session:
            result = await session.execute(
                select(SaleModel).where(SaleModel.item_id == item_id, SaleModel.sold_at >= since)
            )
            return [_sale_from_model(model) for model in result.scalars().all()]

    async def list_by_collection(
        self, collection_id: str, since: datetime, limit: int = 1000
    ) -> Sequence[SaleEvent]:
        async with self._sessions() as session:
            result = await session.execute(
                select(SaleModel)
                .where(SaleModel.collection_id == collection_id, SaleModel.sold_at >= since)
                .order_by(SaleModel.sold_at.desc())
                .limit(limit)
            )
            return [_sale_from_model(model) for model in result.scalars().all()]


class PostgresCollectionRepository:
    """CollectionRepository: карточка коллекции по on-chain-адресу."""

    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def get(self, address: str) -> Collection | None:
        async with self._sessions() as session:
            model = await session.get(CollectionModel, address)
            return None if model is None else _collection_from_model(model)

    async def save(self, collection: Collection) -> None:
        async with self._sessions() as session:
            await session.merge(_collection_to_model(collection))
            await session.commit()

    async def list_names(self) -> list[str]:
        """Имена всех известных коллекций (каталог для детектора клонов)."""
        async with self._sessions() as session:
            result = await session.execute(select(CollectionModel.name))
            return list(result.scalars().all())


# ── репозитории valuation ───────────────────────────────────────────────


class PostgresFeatureStore:
    """FeatureStorePort: снимок price_stats по collection_id (upsert)."""

    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def load(self, collection_id: str) -> CollectionFeatures | None:
        async with self._sessions() as session:
            model = await session.get(PriceStatsModel, collection_id)
            return None if model is None else _features_from_model(model)

    async def save(self, features: CollectionFeatures) -> None:
        async with self._sessions() as session:
            await session.merge(_features_to_model(features))
            await session.commit()


class PostgresValuationRepository:
    """ValuationRepository: оценки по listing_id (аудит, ТЗ §5)."""

    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def save(self, listing_id: str, estimate: FairPriceEstimate) -> str:
        model = _estimate_to_model(listing_id, estimate)
        async with self._sessions() as session:
            await session.merge(model)
            await session.commit()
        return model.id

    async def get_by_listing(self, listing_id: str) -> FairPriceEstimate | None:
        async with self._sessions() as session:
            result = await session.execute(
                select(ValuationModel).where(ValuationModel.listing_id == listing_id)
            )
            model = result.scalars().first()
            return None if model is None else _estimate_from_model(model)


# ── репозитории alerts ──────────────────────────────────────────────────


class PostgresAlertRepository:
    """AlertRepository: save/get/list_by_user/дедуп/rate limit/list_recent."""

    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def save(self, alert: Alert) -> None:
        async with self._sessions() as session:
            await session.merge(_alert_to_model(alert))
            await session.commit()

    async def get(self, alert_id: str) -> Alert | None:
        async with self._sessions() as session:
            model = await session.get(AlertModel, alert_id)
            return None if model is None else _alert_from_model(model)

    async def list_by_user(self, user_id: str) -> Sequence[Alert]:
        async with self._sessions() as session:
            result = await session.execute(select(AlertModel).where(AlertModel.user_id == user_id))
            return [_alert_from_model(model) for model in result.scalars().all()]

    async def list_recent(self, since: datetime) -> Sequence[Alert]:
        async with self._sessions() as session:
            result = await session.execute(select(AlertModel).where(AlertModel.sent_at >= since))
            return [_alert_from_model(model) for model in result.scalars().all()]

    async def find_recent_by_dedup(
        self, user_id: str, dedup_key: str, since_ts: datetime
    ) -> Alert | None:
        async with self._sessions() as session:
            result = await session.execute(
                select(AlertModel)
                .where(
                    AlertModel.user_id == user_id,
                    AlertModel.dedup_key == dedup_key,
                    AlertModel.sent_at >= since_ts,
                )
                .order_by(AlertModel.sent_at.desc())
                .limit(1)
            )
            model = result.scalars().first()
            return None if model is None else _alert_from_model(model)

    async def count_recent(self, user_id: str, since: datetime) -> int:
        async with self._sessions() as session:
            result = await session.execute(
                select(AlertModel).where(AlertModel.user_id == user_id, AlertModel.sent_at >= since)
            )
            return len(result.scalars().all())


class PostgresDecisionRepository:
    """DecisionRepository (alerts): решения по алертам."""

    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def save(self, decision: Decision) -> None:
        async with self._sessions() as session:
            await session.merge(
                DecisionModel(
                    id=decision.id,
                    alert_id=decision.alert_id,
                    user_id=decision.user_id,
                    action=decision.action,
                    latency_ms=decision.latency_ms,
                    created_at=decision.created_at,
                )
            )
            await session.commit()

    async def list_by_alert(self, alert_id: str) -> list[Decision]:
        async with self._sessions() as session:
            result = await session.execute(
                select(DecisionModel).where(DecisionModel.alert_id == alert_id)
            )
            return [
                Decision(
                    id=model.id,
                    alert_id=model.alert_id,
                    user_id=model.user_id,
                    action=model.action,
                    latency_ms=model.latency_ms,
                    created_at=model.created_at,
                )
                for model in result.scalars().all()
            ]

    async def list_by_user(self, user_id: str) -> list[Decision]:
        async with self._sessions() as session:
            result = await session.execute(
                select(DecisionModel).where(DecisionModel.user_id == user_id)
            )
            return [
                Decision(
                    id=model.id,
                    alert_id=model.alert_id,
                    user_id=model.user_id,
                    action=model.action,
                    latency_ms=model.latency_ms,
                    created_at=model.created_at,
                )
                for model in result.scalars().all()
            ]


class PostgresOutcomeRepository:
    """OutcomeRepository: исходы алертов (трекинг, ТЗ §5)."""

    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def save(self, outcome: Outcome) -> None:
        async with self._sessions() as session:
            await session.merge(_outcome_to_model(outcome))
            await session.commit()

    async def get_by_alert(self, alert_id: str) -> Outcome | None:
        async with self._sessions() as session:
            result = await session.execute(
                select(OutcomeModel).where(OutcomeModel.alert_id == alert_id)
            )
            model = result.scalars().first()
            return None if model is None else _outcome_from_model(model)

    async def list_by_user(self, user_id: str) -> Sequence[Outcome]:
        async with self._sessions() as session:
            result = await session.execute(
                select(OutcomeModel).where(OutcomeModel.user_id == user_id)
            )
            return [_outcome_from_model(model) for model in result.scalars().all()]


# ── репозитории бота (entrypoints/bot/ports.py) ─────────────────────────


class PostgresUserSettingsStore:
    """UserSettingsStore: настройки пользователей (таблица user_settings)."""

    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def get(self, user_id: str) -> UserSettings | None:
        async with self._sessions() as session:
            model = await session.get(UserSettingsModel, user_id)
            if model is None:
                return None
            return UserSettings(
                user_id=model.user_id,
                language=model.language,  # type: ignore[arg-type]
                min_discount=model.min_discount,
                min_confidence=model.min_confidence,
                price_min=TONAmount.from_nano(model.price_min_nano),
                price_max=TONAmount.from_nano(model.price_max_nano),
                min_liquidity=model.min_liquidity,
                max_risk=model.max_risk,
                max_alerts_per_hour=model.max_alerts_per_hour,
                quiet_hours=_quiet_hours_from_json(model.quiet_hours),
                paused=model.paused,
                muted_collections=_strings_from_json(model.muted_collections),
            )

    async def save(self, settings: UserSettings) -> None:
        async with self._sessions() as session:
            await session.merge(
                UserSettingsModel(
                    user_id=settings.user_id,
                    language=settings.language,
                    min_discount=settings.min_discount,
                    min_confidence=settings.min_confidence,
                    price_min_nano=settings.price_min.nano,
                    price_max_nano=settings.price_max.nano,
                    min_liquidity=settings.min_liquidity,
                    max_risk=settings.max_risk,
                    max_alerts_per_hour=settings.max_alerts_per_hour,
                    quiet_hours=_quiet_hours_to_json(settings.quiet_hours),
                    paused=settings.paused,
                    muted_collections=list(settings.muted_collections),
                )
            )
            await session.commit()

    async def list_users(self) -> tuple[str, ...]:
        async with self._sessions() as session:
            result = await session.execute(select(UserSettingsModel.user_id))
            return tuple(result.scalars().all())


class PostgresWatchlistStore:
    """WatchlistStore: user_id → адреса предметов (таблица watchlist)."""

    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def add(self, user_id: str, item_id: str) -> None:
        async with self._sessions() as session:
            await session.merge(WatchlistModel(user_id=user_id, item_id=item_id))
            await session.commit()

    async def list(self, user_id: str) -> tuple[str, ...]:
        async with self._sessions() as session:
            result = await session.execute(
                select(WatchlistModel.item_id).where(WatchlistModel.user_id == user_id)
            )
            return tuple(result.scalars().all())


class PostgresDecisionStore:
    """DecisionStore (бот): запись решений и счётчики для /stats."""

    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def save(self, decision: Decision) -> None:
        async with self._sessions() as session:
            await session.merge(
                DecisionModel(
                    id=decision.id,
                    alert_id=decision.alert_id,
                    user_id=decision.user_id,
                    action=decision.action,
                    latency_ms=decision.latency_ms,
                    created_at=decision.created_at,
                )
            )
            await session.commit()

    async def count_by_user(self, user_id: str) -> dict[str, int]:
        async with self._sessions() as session:
            result = await session.execute(
                select(DecisionModel.action).where(DecisionModel.user_id == user_id)
            )
            counts: dict[str, int] = {}
            for action in result.scalars().all():
                counts[action] = counts.get(action, 0) + 1
            return counts


class PostgresAlertRegistry:
    """AlertRegistry: alert_id → контекст алерта (для кнопок)."""

    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def get(self, alert_id: str) -> dict[str, object] | None:
        async with self._sessions() as session:
            model = await session.get(AlertRegistryModel, alert_id)
            return None if model is None else dict(model.context)

    async def put(self, alert_id: str, context: dict[str, object]) -> None:
        async with self._sessions() as session:
            await session.merge(AlertRegistryModel(alert_id=alert_id, context=dict(context)))
            await session.commit()
