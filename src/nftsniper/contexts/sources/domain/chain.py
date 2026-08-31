"""On-chain данные (источник истины по ценам, ТЗ §3)."""

from dataclasses import dataclass
from datetime import datetime

from nftsniper.shared.domain.base import ValueObject
from nftsniper.shared.money import TONAmount


@dataclass(frozen=True, slots=True)
class NftTransfer(ValueObject):
    """Трансфер NFT в блокчейне. ``amount`` — сумма продажи, если по
    данным источника установлена (sale-контракт)."""

    tx_hash: str
    nft_address: str
    from_address: str
    to_address: str
    timestamp: datetime
    amount: TONAmount | None = None


@dataclass(frozen=True, slots=True)
class WalletInfo(ValueObject):
    """Метаданные кошелька для risk-фильтров.

    ``created_at`` — время первого транзакта (возраст кошелька);
    ``total_inflow`` — суммарный входящий объём (Decimal TON).
    """

    address: str
    created_at: datetime | None = None
    total_inflow: TONAmount | None = None
