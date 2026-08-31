"""Листинг предмета на маркетплейсе."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from nftsniper.contexts.sources.domain.item import Item
from nftsniper.contexts.sources.domain.marketplace import Marketplace
from nftsniper.shared.domain.base import Entity
from nftsniper.shared.money import TONAmount
from nftsniper.shared.ton_address import TonAddress


class ListingStatus(StrEnum):
    ACTIVE = "active"
    SOLD = "sold"
    CANCELLED = "cancelled"
    EXPIRED = "expired"


@dataclass(frozen=True, slots=True)
class Listing(Entity):
    """Активное/завершённое предложение купить предмет.

    Иммутабилен: смена статуса = новый объект (методы ``mark_*``).
    ``id`` — внутренний идентификатор (уникальный индекс
    (marketplace, external_id) обеспечивает идемпотентность, ТЗ §5).
    """

    id: str
    external_id: str
    marketplace: Marketplace
    item: Item
    price: TONAmount
    seller: TonAddress
    currency: str = "ton"
    listed_at: datetime | None = None
    closed_at: datetime | None = None
    status: ListingStatus = ListingStatus.ACTIVE
    raw: dict[str, object] | None = None

    def __post_init__(self) -> None:
        if self.status not in (
            ListingStatus.ACTIVE,
            ListingStatus.SOLD,
            ListingStatus.CANCELLED,
            ListingStatus.EXPIRED,
        ):
            msg = f"неизвестный статус листинга: {self.status}"
            raise ValueError(msg)

    # ── ключи ───────────────────────────────────────────────────────────

    @property
    def dedup_key(self) -> str:
        """Ключ дедупликации (ТЗ §6): marketplace + внешний id листинга."""
        return f"{self.marketplace.value}:{self.external_id}"

    @property
    def is_active(self) -> bool:
        return self.status is ListingStatus.ACTIVE

    # ── переходы состояния ──────────────────────────────────────────────

    def _replace(self, **changes: object) -> Listing:
        base: dict[str, object] = {
            "id": self.id,
            "external_id": self.external_id,
            "marketplace": self.marketplace,
            "item": self.item,
            "price": self.price,
            "seller": self.seller,
            "currency": self.currency,
            "listed_at": self.listed_at,
            "closed_at": self.closed_at,
            "status": self.status,
            "raw": self.raw,
        }
        base.update(changes)
        return Listing(**base)  # type: ignore[arg-type]

    def mark_sold(self, *, at: datetime, price: TONAmount | None = None) -> Listing:
        if not self.is_active:
            msg = f"нельзя продать листинг в статусе {self.status.value}"
            raise ValueError(msg)
        return self._replace(
            status=ListingStatus.SOLD,
            closed_at=at,
            price=price if price is not None else self.price,
        )

    def mark_cancelled(self, *, at: datetime) -> Listing:
        if not self.is_active:
            msg = f"нельзя отменить листинг в статусе {self.status.value}"
            raise ValueError(msg)
        return self._replace(status=ListingStatus.CANCELLED, closed_at=at)

    def mark_expired(self, *, at: datetime) -> Listing:
        if not self.is_active:
            msg = f"нельзя истечь листинг в статусе {self.status.value}"
            raise ValueError(msg)
        return self._replace(status=ListingStatus.EXPIRED, closed_at=at)

    def update_price(self, *, price: TONAmount) -> Listing:
        """Изменение цены на маркетплейсе (только для активных)."""
        if not self.is_active:
            msg = f"нельзя менять цену листинга в статусе {self.status.value}"
            raise ValueError(msg)
        return self._replace(price=price)
