"""Сделка OTC: прямая оплата листинга пересылкой TON продавцу.

Иммутабельный: каждый переход состояния возвращает новый OtcDeal.
Комментарий в пересылке == id сделки (короткий ASCII) — продавец и
бот сопоставляют платёж однозначно.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from nftsniper.shared.ton_address import TonAddress


class OtcStatus(StrEnum):
    AWAITING_PAYMENT = "awaiting_payment"
    PAID = "paid"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    EXPIRED = "expired"


class OtcError(RuntimeError):
    """Недопустимый переход состояния или неизвестная сущность."""


class OtcNotFoundError(OtcError):
    """Сделка не найдена."""


class ItemNotFoundError(OtcError):
    """Предмет не найден."""


@dataclass(frozen=True, slots=True)
class OtcDeal:
    id: str  # "OTC-K3P9XZ"
    item_id: str
    item_name: str
    collection_name: str
    seller: TonAddress
    buyer: TonAddress
    amount_nano: int
    comment: str  # == id, уходит в payload пересылки
    status: OtcStatus
    created_at: datetime
    expires_at: datetime
    paid_tx_hash: str | None = None
    paid_at: datetime | None = None
    nft_tx_hash: str | None = None
    completed_at: datetime | None = None

    def __post_init__(self) -> None:
        if self.comment != self.id:
            msg = "comment сделки должен совпадать с её id"
            raise OtcError(msg)

    # ── ссылки на оплату ────────────────────────────────────────────────

    @property
    def payment_url(self) -> str:
        return self.seller.payment_url(self.amount_nano, self.comment)

    @property
    def tonkeeper_url(self) -> str:
        return self.seller.tonkeeper_url(self.amount_nano, self.comment)

    @property
    def universal_link(self) -> str:
        return self.seller.universal_link(self.amount_nano, self.comment)

    def is_expired(self, now: datetime) -> bool:
        return self.status is OtcStatus.AWAITING_PAYMENT and now >= self.expires_at

    # ── переходы состояния ──────────────────────────────────────────────

    def mark_paid(self, tx_hash: str, now: datetime) -> OtcDeal:
        if self.status is not OtcStatus.AWAITING_PAYMENT:
            msg = f"нельзя пометить paid из состояния {self.status.value}"
            raise OtcError(msg)
        if now > self.expires_at:
            msg = "срок оплаты истёк"
            raise OtcError(msg)
        return replace_paid(self, tx_hash=tx_hash, paid_at=now)

    def mark_completed(self, nft_tx_hash: str | None, now: datetime) -> OtcDeal:
        if self.status is not OtcStatus.PAID:
            msg = f"нельзя закрыть сделку из состояния {self.status.value}"
            raise OtcError(msg)
        return OtcDeal(
            id=self.id,
            item_id=self.item_id,
            item_name=self.item_name,
            collection_name=self.collection_name,
            seller=self.seller,
            buyer=self.buyer,
            amount_nano=self.amount_nano,
            comment=self.comment,
            status=OtcStatus.COMPLETED,
            created_at=self.created_at,
            expires_at=self.expires_at,
            paid_tx_hash=self.paid_tx_hash,
            paid_at=self.paid_at,
            nft_tx_hash=nft_tx_hash,
            completed_at=now,
        )

    def cancel(self, now: datetime) -> OtcDeal:
        if self.status is not OtcStatus.AWAITING_PAYMENT:
            msg = f"нельзя отменить сделку в состоянии {self.status.value}"
            raise OtcError(msg)
        return self._with_status(OtcStatus.CANCELLED, now)

    def expire(self, now: datetime) -> OtcDeal:
        if self.status is not OtcStatus.AWAITING_PAYMENT:
            msg = f"нельзя истечь сделку в состоянии {self.status.value}"
            raise OtcError(msg)
        return self._with_status(OtcStatus.EXPIRED, now)

    def _with_status(self, status: OtcStatus, now: datetime) -> OtcDeal:
        return OtcDeal(
            id=self.id,
            item_id=self.item_id,
            item_name=self.item_name,
            collection_name=self.collection_name,
            seller=self.seller,
            buyer=self.buyer,
            amount_nano=self.amount_nano,
            comment=self.comment,
            status=status,
            created_at=self.created_at,
            expires_at=self.expires_at,
        )


def replace_paid(deal: OtcDeal, *, tx_hash: str, paid_at: datetime) -> OtcDeal:
    return OtcDeal(
        id=deal.id,
        item_id=deal.item_id,
        item_name=deal.item_name,
        collection_name=deal.collection_name,
        seller=deal.seller,
        buyer=deal.buyer,
        amount_nano=deal.amount_nano,
        comment=deal.comment,
        status=OtcStatus.PAID,
        created_at=deal.created_at,
        expires_at=deal.expires_at,
        paid_tx_hash=tx_hash,
        paid_at=paid_at,
    )
