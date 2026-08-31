"""Use cases OTC: создание сделки, проверка оплаты, подтверждение NFT."""

import secrets
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from nftsniper.contexts.otc.domain.deal import (
    ItemNotFoundError,
    OtcDeal,
    OtcNotFoundError,
    OtcStatus,
    replace_paid,
)
from nftsniper.contexts.otc.domain.item import ItemSnapshot
from nftsniper.contexts.otc.ports import (
    ItemSourcePort,
    OtcDealRepository,
    QrCodePort,
    TransferObservationPort,
)
from nftsniper.shared.money import format_ton
from nftsniper.shared.ton_address import TonAddress, TonAddressError, parse_address

# Без легкопутанных символов (0/O, 1/I/L): id уходит в комментарий пересылки
_ID_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
_ID_LEN = 6


def generate_deal_id() -> str:
    return "OTC-" + "".join(secrets.choice(_ID_ALPHABET) for _ in range(_ID_LEN))


def parse_buyer_address(text: str) -> TonAddress:
    """Валидация адреса покупателя; поднимает TonAddressError."""
    address = parse_address(text)
    if address.raw_bytes == b"\x00" * 32:
        msg = "нулевой адрес не подходит"
        raise TonAddressError(msg)
    return address


@dataclass(frozen=True, slots=True)
class PaymentPayload:
    """Всё, что нужно мини-аппу для экрана оплаты (без float)."""

    seller_address: str
    seller_address_short: str
    amount_nano: str
    amount_ton: str
    comment: str
    qr_url: str
    qr_data_uri: str
    tonkeeper_url: str
    universal_link: str


@dataclass(frozen=True, slots=True)
class ItemSnapshotView:
    """Компактная карточка предмета для списков."""

    id: str
    name: str
    collection_name: str
    price_ton: str
    price_nano: str
    image_url: str
    rarity_note: str
    discount_pct: str


class OtcService:
    def __init__(
        self,
        items: ItemSourcePort,
        deals: OtcDealRepository,
        transfers: TransferObservationPort,
        qr: QrCodePort,
        *,
        ttl: timedelta = timedelta(minutes=30),
        now: Callable[[], datetime] | None = None,
        id_gen: Callable[[], str] | None = None,
    ) -> None:
        self._items = items
        self._deals = deals
        self._transfers = transfers
        self._qr = qr
        self._ttl = ttl
        self._now = now if now is not None else (lambda: datetime.now(UTC))
        self._id_gen = id_gen if id_gen is not None else generate_deal_id

    # ── чтение ──────────────────────────────────────────────────────────

    async def list_items(self) -> tuple[ItemSnapshotView, ...]:
        items = await self._items.get_items()
        return tuple(_to_view(item) for item in items)

    async def get_item(self, item_id: str) -> ItemSnapshot:
        item = await self._items.get_item(item_id)
        if item is None:
            raise ItemNotFoundError(item_id)
        return item

    async def get_deal(self, deal_id: str) -> OtcDeal:
        deal = await self._deals.get(deal_id)
        if deal is None:
            raise OtcNotFoundError(deal_id)
        return self._maybe_expire(deal)

    def payload(self, deal: OtcDeal) -> PaymentPayload:
        return PaymentPayload(
            seller_address=deal.seller.user_friendly(bounceable=False),
            seller_address_short=deal.seller.short,
            amount_nano=str(deal.amount_nano),
            amount_ton=format_ton(deal.amount_nano),
            comment=deal.comment,
            qr_url=deal.payment_url,
            qr_data_uri=self._qr.make(deal.payment_url),
            tonkeeper_url=deal.tonkeeper_url,
            universal_link=deal.universal_link,
        )

    # ── действия ────────────────────────────────────────────────────────

    async def create_deal(self, item_id: str, buyer_address: str) -> OtcDeal:
        item = await self._items.get_item(item_id)
        if item is None:
            raise ItemNotFoundError(item_id)
        buyer = parse_buyer_address(buyer_address)
        deal_id = self._id_gen()
        now = self._now()
        deal = OtcDeal(
            id=deal_id,
            item_id=item.id,
            item_name=item.name,
            collection_name=item.collection_name,
            seller=item.seller,
            buyer=buyer,
            amount_nano=item.price_nano,
            comment=deal_id,
            status=OtcStatus.AWAITING_PAYMENT,
            created_at=now,
            expires_at=now + self._ttl,
        )
        await self._deals.add(deal)
        return deal

    async def check_payment(self, deal_id: str) -> OtcDeal:
        deal = await self.get_deal(deal_id)
        now = self._now()
        if deal.is_expired(now):
            deal = deal.expire(now)
            await self._deals.save(deal)
            return deal
        if deal.status is not OtcStatus.AWAITING_PAYMENT:
            return deal
        transfer = await self._transfers.find_transfer(
            to=deal.seller,
            amount_nano=deal.amount_nano,
            comment=deal.comment,
            since=deal.created_at,
        )
        if transfer is None:
            return deal
        deal = replace_paid(deal, tx_hash=transfer.tx_hash, paid_at=now)
        await self._deals.save(deal)
        return deal

    async def cancel_deal(self, deal_id: str) -> OtcDeal:
        deal = await self.get_deal(deal_id)
        deal = deal.cancel(self._now())
        await self._deals.save(deal)
        return deal

    async def confirm_nft_received(self, deal_id: str, nft_tx_hash: str | None = None) -> OtcDeal:
        deal = await self.get_deal(deal_id)
        deal = deal.mark_completed(nft_tx_hash, self._now())
        await self._deals.save(deal)
        return deal

    async def sweep_expired(self) -> int:
        now = self._now()
        count = 0
        for deal in list(await self._deals.list_active()):
            if deal.status is OtcStatus.AWAITING_PAYMENT and now >= deal.expires_at:
                await self._deals.save(deal.expire(now))
                count += 1
        return count

    def _maybe_expire(self, deal: OtcDeal) -> OtcDeal:
        if deal.is_expired(self._now()):
            return deal.expire(self._now())
        return deal


def _to_view(item: ItemSnapshot) -> ItemSnapshotView:
    return ItemSnapshotView(
        id=item.id,
        name=item.name,
        collection_name=item.collection_name,
        price_ton=format_ton(item.price_nano),
        price_nano=str(item.price_nano),
        image_url=item.image_url,
        rarity_note=item.rarity_note,
        discount_pct=item.valuation.discount_pct,
    )
