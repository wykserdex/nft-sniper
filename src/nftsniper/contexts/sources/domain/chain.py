"""On-chain данные (источник истины по ценам, ТЗ §3)."""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

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


@dataclass(frozen=True, slots=True)
class SaleVerification(ValueObject):
    """Результат сверки продажи с on-chain (ТЗ §3).

    ``discrepancy`` — относительное расхождение цены
    ``|on_chain − marketplace| / on_chain`` (Decimal, None если on-chain
    сумма не установлена). ``matches`` — цена сходится в пределах допуска
    (по умолчанию 1%, ТЗ §3). ``reason`` — код причины расхождения:
    ``transfer_not_found`` / ``no_onchain_amount`` / ``price_mismatch`` /
    ``zero_onchain_amount``; None при совпадении.
    """

    sale_id: str
    marketplace_amount: TONAmount
    on_chain_amount: TONAmount | None = None
    discrepancy: Decimal | None = None
    matches: bool = False
    reason: str | None = None
