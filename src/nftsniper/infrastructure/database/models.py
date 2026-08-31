"""ORM-модели (таблицы ТЗ §5) — SQLAlchemy 2.0 + asyncpg.

Соглашения маппинга домен → БД:

- **Деньги** — ``*_nano`` BIGINT (nanoTON, int): TONAmount ↔ nano. Никаких
  float в деньгах (ТЗ: деньги — Decimal/nanoTON).
- **Адреса** — ``raw_str`` (``0:hex64``): TonAddress ↔ строка, без потерь.
- **Enum'ы** (Marketplace, ListingStatus, EstimationMethod) — ``.value`` в String.
- **JSONB** — трейты, raw-контракты, объяснения оценок, история floor,
  quiet_hours, muted_collections.
- Внешние ключи не навешиваем: границы агрегатов пересекаются, upsert'ы
  идут пачками (item перед listing); целостность держит прикладной слой.
  Индексы — на колонках выборок (dedup, rate limit, трекинг исходов).

Метадата регистрируется в ``migrations/env.py`` (``target_metadata``) и
создаётся миграцией ``0002``.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import BigInteger, Boolean, DateTime, Index, Integer, Numeric, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from nftsniper.infrastructure.database.engine import Base

# Деньги: 9 знаков дробной части, до 10^27 nanoTON — BIGINT хватает.
# Доли (дискаунт/confidence/ликвидность/риск) — Numeric с запасом.
_MONEY = BigInteger
_FRACTION = Numeric(38, 18)


class CollectionModel(Base):
    """``collections`` — ``id`` = on-chain-адрес контракта коллекции."""

    __tablename__ = "collections"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    slug: Mapped[str] = mapped_column(String, nullable=False)
    marketplace: Mapped[str | None] = mapped_column(String, nullable=True)
    verified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    items_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    royalty_bps: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    risk_score: Mapped[Decimal | None] = mapped_column(Numeric(10, 8), nullable=True)


class ItemModel(Base):
    """``items`` — ``id`` = on-chain-адрес NFT (источник истины, ТЗ §5)."""

    __tablename__ = "items"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    collection_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    index: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    name: Mapped[str] = mapped_column(String, nullable=False)
    traits: Mapped[list[dict[str, object]]] = mapped_column(JSONB, nullable=False, default=list)
    rarity_rank: Mapped[Decimal | None] = mapped_column(Numeric(10, 8), nullable=True)
    rarity_score: Mapped[Decimal | None] = mapped_column(Numeric(10, 8), nullable=True)
    media_url: Mapped[str | None] = mapped_column(String, nullable=True)


class ListingModel(Base):
    """``listings`` — ``id`` = ``marketplace:external_id`` (идемпотентность, ТЗ §5)."""

    __tablename__ = "listings"
    __table_args__ = (Index("ix_listings_dedup", "marketplace", "external_id", unique=True),)

    id: Mapped[str] = mapped_column(String, primary_key=True)
    external_id: Mapped[str] = mapped_column(String, nullable=False)
    marketplace: Mapped[str] = mapped_column(String, nullable=False)
    item_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    price_nano: Mapped[int] = mapped_column(_MONEY, nullable=False)
    currency: Mapped[str] = mapped_column(String, nullable=False, default="ton")
    seller: Mapped[str] = mapped_column(String, nullable=False)  # raw_str
    listed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String, nullable=False, default="active")
    raw: Mapped[dict[str, object] | None] = mapped_column(JSONB, nullable=True)


class SaleModel(Base):
    """``sales`` — продажи; ``sold_at`` индексирован (окна статистики/риска)."""

    __tablename__ = "sales"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    item_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    collection_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    price_nano: Mapped[int] = mapped_column(_MONEY, nullable=False)
    buyer: Mapped[str] = mapped_column(String, nullable=False)
    seller: Mapped[str] = mapped_column(String, nullable=False)
    tx_hash: Mapped[str] = mapped_column(String, nullable=False)
    sold_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    marketplace: Mapped[str | None] = mapped_column(String, nullable=True)
    is_suspicious: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class PriceStatsModel(Base):
    """``price_stats`` — снимок статистики коллекции (upsert по collection_id)."""

    __tablename__ = "price_stats"

    collection_id: Mapped[str] = mapped_column(String, primary_key=True)
    floor_p5_nano: Mapped[int] = mapped_column(_MONEY, nullable=False)
    median_7d_nano: Mapped[int] = mapped_column(_MONEY, nullable=False)
    volume_24h_nano: Mapped[int] = mapped_column(_MONEY, nullable=False)
    sales_per_day: Mapped[Decimal] = mapped_column(_FRACTION, nullable=False)
    sales_7d: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    listings_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    floor_24h_change: Mapped[Decimal] = mapped_column(_FRACTION, nullable=False)
    floor_7d_change: Mapped[Decimal] = mapped_column(_FRACTION, nullable=False)
    as_of: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    floor_history: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)


class ValuationModel(Base):
    """``valuations`` — оценка листинга (аудит; одна на листинг, ТЗ §5)."""

    __tablename__ = "valuations"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    listing_id: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    fair_price_nano: Mapped[int] = mapped_column(_MONEY, nullable=False)
    confidence: Mapped[Decimal] = mapped_column(_FRACTION, nullable=False)
    method: Mapped[str] = mapped_column(String, nullable=False)
    lower_bound_nano: Mapped[int] = mapped_column(_MONEY, nullable=False)
    upper_bound_nano: Mapped[int] = mapped_column(_MONEY, nullable=False)
    sample_size: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    explanation: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    model_version: Mapped[str] = mapped_column(String, nullable=False, default="0.0.0")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class AlertModel(Base):
    """``alerts`` — отправленные алерты (дедуп по user+dedup_key, rate limit)."""

    __tablename__ = "alerts"
    __table_args__ = (
        Index("ix_alerts_user_sent", "user_id", "sent_at"),
        Index("ix_alerts_user_dedup", "user_id", "dedup_key", "sent_at"),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True)
    user_id: Mapped[str] = mapped_column(String, nullable=False)
    listing_id: Mapped[str] = mapped_column(String, nullable=False)
    valuation_id: Mapped[str] = mapped_column(String, nullable=False, default="")
    dedup_key: Mapped[str] = mapped_column(String, nullable=False)
    sent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    message_id: Mapped[str | None] = mapped_column(String, nullable=True)


class DecisionModel(Base):
    """``decisions`` — решения пользователя (action: taken/skipped/watch/muted)."""

    __tablename__ = "decisions"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    alert_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    user_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    action: Mapped[str] = mapped_column(String, nullable=False)
    latency_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class OutcomeModel(Base):
    """``outcomes`` — исходы алертов (трекинг 1h/24h/7d, ТЗ §5)."""

    __tablename__ = "outcomes"
    __table_args__ = (Index("ix_outcomes_user", "user_id"),)

    id: Mapped[str] = mapped_column(String, primary_key=True)
    alert_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    user_id: Mapped[str] = mapped_column(String, nullable=False)
    listing_id: Mapped[str] = mapped_column(String, nullable=False)
    alert_price_nano: Mapped[int] = mapped_column(_MONEY, nullable=False)
    fair_price_nano: Mapped[int] = mapped_column(_MONEY, nullable=False)
    discount: Mapped[Decimal] = mapped_column(_FRACTION, nullable=False)
    price_after_1h_nano: Mapped[int | None] = mapped_column(_MONEY, nullable=True)
    price_after_24h_nano: Mapped[int | None] = mapped_column(_MONEY, nullable=True)
    price_after_7d_nano: Mapped[int | None] = mapped_column(_MONEY, nullable=True)
    sold_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    sold_price_nano: Mapped[int | None] = mapped_column(_MONEY, nullable=True)
    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class UserSettingsModel(Base):
    """``user_settings`` — пороги и предпочтения пользователя (ТЗ §5)."""

    __tablename__ = "user_settings"

    user_id: Mapped[str] = mapped_column(String, primary_key=True)
    language: Mapped[str] = mapped_column(String, nullable=False, default="ru")
    min_discount: Mapped[Decimal] = mapped_column(_FRACTION, nullable=False)
    min_confidence: Mapped[Decimal] = mapped_column(_FRACTION, nullable=False)
    price_min_nano: Mapped[int] = mapped_column(_MONEY, nullable=False)
    price_max_nano: Mapped[int] = mapped_column(_MONEY, nullable=False)
    min_liquidity: Mapped[Decimal] = mapped_column(_FRACTION, nullable=False)
    max_risk: Mapped[Decimal] = mapped_column(_FRACTION, nullable=False)
    max_alerts_per_hour: Mapped[int] = mapped_column(Integer, nullable=False, default=20)
    quiet_hours: Mapped[list[list[int]]] = mapped_column(JSONB, nullable=False, default=list)
    paused: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    muted_collections: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)


class WatchlistModel(Base):
    """``watchlist`` — вотчлист пользователя (user_id, item_id)."""

    __tablename__ = "watchlist"

    user_id: Mapped[str] = mapped_column(String, primary_key=True)
    item_id: Mapped[str] = mapped_column(String, primary_key=True)


class AlertRegistryModel(Base):
    """``alert_registry`` — контекст алерта для кнопок (диплинк/мьют/вотчлист)."""

    __tablename__ = "alert_registry"

    alert_id: Mapped[str] = mapped_column(String, primary_key=True)
    context: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False, default=dict)
