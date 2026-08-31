"""Мгновенное фото предмета для мини-аппа.

Пока источник — sample-адаптер; когда поднимутся contexts/sources
 — маппинг Listing/Item/price_stats в ItemSnapshot.
Все цены — int nanoTON, остальные строки — для человека (без float).
"""

from dataclasses import dataclass

from nftsniper.shared.ton_address import TonAddress


@dataclass(frozen=True, slots=True)
class Trait:
    name: str
    value: str
    rarity: str  # доля предметов с таким значением: "0.4%" или "—"


@dataclass(frozen=True, slots=True)
class ValuationSnapshot:
    """Срез оценки fair price (ядро — contexts/valuation)."""

    fair_price_nano: int
    discount_pct: str  # "-42%"
    confidence: str  # "0.78" — строка Decimal, не float
    explanation: tuple[str, ...]  # человекочитаемые причины


@dataclass(frozen=True, slots=True)
class PricePoint:
    days_ago: int
    price_nano: int


@dataclass(frozen=True, slots=True)
class ItemSnapshot:
    id: str
    name: str
    collection_name: str
    image_url: str
    price_nano: int
    price_usd_approx: str  # "~$580" — на момент снапшота
    seller: TonAddress
    seller_wallet_age: str  # "2 дня"
    floor_ton: str
    floor_24h_change: str  # "-3%"
    median_7d_ton: str
    sales_7d: int
    liquidity_per_day: str  # "2.4"
    listing_age: str  # "11 сек"
    rarity_note: str  # "топ 8% по коллекции"
    traits: tuple[Trait, ...]
    valuation: ValuationSnapshot
    risk_flags: tuple[str, ...]
    price_history: tuple[PricePoint, ...]
