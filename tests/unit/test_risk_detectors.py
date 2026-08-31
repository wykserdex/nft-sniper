"""Детекторы риска: юнит-тесты чистых функций."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from nftsniper.contexts.risk.application.detectors import (
    WalletEdge,
    detect_auction_mismatch,
    detect_broken_metadata,
    detect_clone_collection,
    detect_fake_sales,
    detect_low_volume,
    detect_royalty_impact,
    detect_seller_risk,
    detect_wash_trading,
    median_price,
    net_price,
    normalize_confusables,
)
from nftsniper.contexts.risk.domain.risk import RiskFlag, RiskSeverity
from nftsniper.contexts.sources.domain.chain import WalletInfo
from nftsniper.contexts.sources.domain.sale import SaleEvent
from nftsniper.shared.money import TONAmount
from nftsniper.shared.ton_address import TonAddress

D = Decimal
NOW = datetime(2026, 8, 31, 12, 0, 0, tzinfo=UTC)
A = TonAddress(workchain=0, raw_bytes=bytes([0xA1]) * 32)
B = TonAddress(workchain=0, raw_bytes=bytes([0xB2]) * 32)
C = TonAddress(workchain=0, raw_bytes=bytes([0xC3]) * 32)


def _sale(
    idx: int,
    price: str,
    *,
    buyer: TonAddress = B,
    seller: TonAddress = A,
    sold_at: datetime | None = None,
) -> SaleEvent:
    return SaleEvent(
        id=f"tx-{idx}",
        item_id=f"item-{idx}",
        collection_id="coll",
        price=TONAmount.from_ton(D(price)),
        buyer=buyer,
        seller=seller,
        tx_hash=f"tx-{idx}",
        sold_at=sold_at if sold_at is not None else NOW - timedelta(hours=idx),
        marketplace=None,
    )


def _code(flag: RiskFlag | None) -> str | None:
    return None if flag is None else flag.code


# ── unicode-подмены и клоны ─────────────────────────────────────────────


def test_normalize_confusables_maps_cyrillic_and_greek() -> None:
    assert normalize_confusables("Теlegram") == "telegram"  # «е» — кириллица
    assert normalize_confusables("Рunks") == "punks"  # «Р» — кириллица
    assert normalize_confusables("αlpha") == "alpha"


def test_detect_clone_homoglyph() -> None:
    flag = detect_clone_collection("Теlegram Numbers", ["Telegram Numbers"])
    assert _code(flag) == "CLONE_COLLECTION"
    assert flag is not None
    assert flag.severity == RiskSeverity.HIGH


def test_detect_clone_typo_similarity() -> None:
    flag = detect_clone_collection("Anonymous Telegram Numbrs", ["Anonymous Telegram Numbers"])
    assert _code(flag) == "CLONE_COLLECTION"


def test_detect_clone_same_collection_not_flagged() -> None:
    assert detect_clone_collection("Telegram Numbers", ["Telegram Numbers"]) is None


def test_detect_clone_distinct_name_not_flagged() -> None:
    assert detect_clone_collection("Punk Skulls", ["Telegram Numbers"]) is None


# ── объём ──────────────────────────────────────────────────────────────


def test_detect_low_volume() -> None:
    assert _code(detect_low_volume(2)) == "LOW_VOLUME"
    assert detect_low_volume(3) is None
    assert detect_low_volume(20) is None


# ── метаданные и медиа ─────────────────────────────────────────────────


def test_detect_broken_metadata_empty_name() -> None:
    assert _code(detect_broken_metadata("")) == "BROKEN_METADATA"
    assert _code(detect_broken_metadata("   ")) == "BROKEN_METADATA"


def test_detect_broken_metadata_unavailable_media() -> None:
    assert _code(detect_broken_metadata("Fluffy #1", media_available=False)) == "BROKEN_METADATA"
    assert detect_broken_metadata("Fluffy #1", media_available=True) is None
    assert detect_broken_metadata("Fluffy #1", media_available=None) is None


# ── продавец ───────────────────────────────────────────────────────────


def test_detect_seller_fresh() -> None:
    wallet = WalletInfo(address="0:aa", created_at=NOW - timedelta(days=1))
    assert _code(detect_seller_risk(wallet, now=NOW)) == "FRESH_SELLER"


def test_detect_seller_old_and_unknown() -> None:
    wallet = WalletInfo(address="0:aa", created_at=NOW - timedelta(days=60))
    assert detect_seller_risk(wallet, now=NOW) is None

    assert _code(detect_seller_risk(None, now=NOW)) == "UNKNOWN_SELLER"
    assert _code(detect_seller_risk(WalletInfo(address="0:aa"), now=NOW)) == "UNKNOWN_SELLER"


# ── fake-продажи ───────────────────────────────────────────────────────


def test_median_price() -> None:
    sales = [_sale(i, str(10 * (i + 1))) for i in range(5)]  # 10..50
    assert median_price(sales) == TONAmount.from_ton(D("30"))
    assert median_price([]) is None


def test_detect_fake_sales_outlier() -> None:
    sales = [_sale(i, "10") for i in range(10)] + [_sale(99, "500")]
    assert _code(detect_fake_sales(sales)) == "FAKE_SALES"  # 500 > 10 × 10


def test_detect_fake_sales_normal() -> None:
    sales = [_sale(i, str(10 + i)) for i in range(10)]  # 10..19
    assert detect_fake_sales(sales) is None


# ── wash trading (граф кошельков) ──────────────────────────────────────


def test_detect_wash_trading_round_trip() -> None:
    edges = [
        WalletEdge(A.raw_str, B.raw_str, NOW - timedelta(hours=3)),
        WalletEdge(B.raw_str, A.raw_str, NOW - timedelta(hours=1)),
    ]
    assert _code(detect_wash_trading(edges, now=NOW)) == "WASH_TRADING"


def test_detect_wash_trading_ring() -> None:
    edges = [
        WalletEdge(A.raw_str, B.raw_str, NOW - timedelta(hours=5)),
        WalletEdge(B.raw_str, C.raw_str, NOW - timedelta(hours=4)),
        WalletEdge(C.raw_str, A.raw_str, NOW - timedelta(hours=3)),
    ]
    assert _code(detect_wash_trading(edges, now=NOW)) == "WASH_TRADING"


def test_detect_wash_trading_plain_chain_not_flagged() -> None:
    edges = [
        WalletEdge(A.raw_str, B.raw_str, NOW - timedelta(hours=5)),
        WalletEdge(B.raw_str, C.raw_str, NOW - timedelta(hours=4)),
    ]
    assert detect_wash_trading(edges, now=NOW) is None


def test_detect_wash_trading_old_edges_ignored() -> None:
    edges = [
        WalletEdge(A.raw_str, B.raw_str, NOW - timedelta(days=10)),
        WalletEdge(B.raw_str, A.raw_str, NOW - timedelta(days=9)),
    ]
    assert detect_wash_trading(edges, now=NOW) is None  # вне окна 2 дня


# ── аукционы ───────────────────────────────────────────────────────────


def test_detect_auction_mismatch() -> None:
    assert _code(detect_auction_mismatch(True)) == "AUCTION_MISMATCH"
    assert detect_auction_mismatch(False) is None


# ── роялти и комиссии ──────────────────────────────────────────────────


def test_net_price() -> None:
    price = TONAmount.from_ton(D("100"))
    # 5% роялти + 2.5% комиссия = 7.5% → 92.5
    net = net_price(price, royalty_bps=500, marketplace_fee_bps=250)
    assert net == TONAmount.from_ton(D("92.5"))


def test_net_price_rejects_negative_bps() -> None:
    with pytest.raises(ValueError, match="отрицательн"):
        net_price(TONAmount.from_ton(D("100")), royalty_bps=-1, marketplace_fee_bps=0)


def test_detect_royalty_impact() -> None:
    price = TONAmount.from_ton(D("100"))
    # 30% роялти → net 70% < 80% → флаг
    flag = detect_royalty_impact(price, royalty_bps=3000, marketplace_fee_bps=0)
    assert _code(flag) == "ROYALTY_IMPACT"
    assert flag is not None
    assert flag.severity == RiskSeverity.LOW
    # 5% роялти → нет флага
    assert detect_royalty_impact(price, royalty_bps=500, marketplace_fee_bps=0) is None
