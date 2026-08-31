"""Порты OTC-контекста."""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from nftsniper.contexts.otc.domain.deal import OtcDeal
from nftsniper.contexts.otc.domain.item import ItemSnapshot
from nftsniper.shared.ton_address import TonAddress


class ItemSourcePort(Protocol):
    """Источник карточек предметов для мини-аппа."""

    async def get_items(self) -> tuple[ItemSnapshot, ...]: ...

    async def get_item(self, item_id: str) -> ItemSnapshot | None: ...


class OtcDealRepository(Protocol):
    async def add(self, deal: OtcDeal) -> None: ...

    async def get(self, deal_id: str) -> OtcDeal | None: ...

    async def save(self, deal: OtcDeal) -> None: ...

    async def list_active(self) -> Sequence[OtcDeal]: ...


@dataclass(frozen=True, slots=True)
class ObservedTransfer:
    """Пересылка, увиденная наблюдателем (пока dev-стор, позже — on-chain)."""

    from_address: str  # user-friendly
    to_address: str  # user-friendly
    amount_nano: int
    comment: str
    tx_hash: str
    at: datetime


class TransferObservationPort(Protocol):
    """Наблюдение за пересылками на адрес продавца.

    Реальная реализация — через ChainPort (TonAPI/TonCenter):
    входящие переводы с текстовым комментарием-идентификатором сделки.
    """

    async def find_transfer(
        self,
        *,
        to: TonAddress,
        amount_nano: int,
        comment: str,
        since: datetime,
    ) -> ObservedTransfer | None: ...


class QrCodePort(Protocol):
    """QR-код в виде data-URI (SVG/PNG) для мини-аппа."""

    def make(self, data: str) -> str: ...
