"""Pydantic-модели API мини-аппа (Pydantic — только на границе, по ТЗ).

Все суммы — строки: nanoTON как стринг (JS-precision), TON как
десятичная строка. Float в API нет.
"""

from pydantic import BaseModel, Field


class ItemBriefOut(BaseModel):
    id: str
    name: str
    collection_name: str
    price_ton: str
    price_nano: str
    image_url: str
    rarity_note: str
    discount_pct: str


class TraitOut(BaseModel):
    name: str
    value: str
    rarity: str


class ValuationOut(BaseModel):
    fair_price_ton: str
    discount_pct: str
    confidence: str
    explanation: list[str]


class PricePointOut(BaseModel):
    days_ago: int
    price_ton: str


class NftDetailOut(BaseModel):
    id: str
    name: str
    collection_name: str
    image_url: str
    price_ton: str
    price_nano: str
    price_usd_approx: str
    floor_ton: str
    floor_24h_change: str
    median_7d_ton: str
    sales_7d: int
    liquidity_per_day: str
    listing_age: str
    rarity_note: str
    traits: list[TraitOut]
    valuation: ValuationOut
    risk_flags: list[str]
    seller_address: str
    seller_address_short: str
    seller_wallet_age: str
    price_history: list[PricePointOut]


class OtcCreateIn(BaseModel):
    item_id: str
    buyer_address: str


class PaymentOut(BaseModel):
    seller_address: str
    seller_address_short: str
    amount_nano: str
    amount_ton: str
    comment: str
    qr_url: str
    qr_data_uri: str
    tonkeeper_url: str
    universal_link: str


class OtcCreateOut(BaseModel):
    deal_id: str
    status: str
    expires_in_sec: int
    payment: PaymentOut


class OtcStatusOut(BaseModel):
    deal_id: str
    status: str
    amount_ton: str
    seller_address: str
    paid_tx_hash: str | None = None
    nft_tx_hash: str | None = None
    paid_tonscan_url: str | None = None
    nft_tonscan_url: str | None = None


class ConfirmNftIn(BaseModel):
    tx_hash: str | None = Field(default=None, max_length=128)


class DevTransferIn(BaseModel):
    from_address: str
    to_address: str
    amount_nano: int = Field(ge=0)
    comment: str = Field(min_length=1, max_length=64)
