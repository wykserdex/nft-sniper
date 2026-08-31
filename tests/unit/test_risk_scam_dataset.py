"""Acceptance: подготовленный набор скам-кейсов.

Критерий готовности ТЗ §7: «на подготовленном наборе скам-кейсов ловится
не менее 90% при контролируемом уровне ложных срабатываний».

Набор: 11 скам-кейсов (каждый — один тип детектора) + 10 чистых. Прогон через
``compute_risk`` (чистая функция, без I/O). «Пойман» = worst severity в
{MEDIUM, HIGH}. Recall >= 90%, false positive rate <= 10%.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from nftsniper.contexts.risk.application.screen import ScreeningInput, compute_risk
from nftsniper.contexts.risk.domain.risk import RiskScore, RiskSeverity
from nftsniper.contexts.sources.domain.chain import WalletInfo
from nftsniper.contexts.sources.domain.collection import Collection
from nftsniper.contexts.sources.domain.item import Item
from nftsniper.contexts.sources.domain.listing import Listing
from nftsniper.contexts.sources.domain.marketplace import Marketplace
from nftsniper.contexts.sources.domain.sale import SaleEvent
from nftsniper.shared.money import TONAmount
from nftsniper.shared.ton_address import TonAddress

D = Decimal
NOW = datetime(2026, 8, 31, 12, 0, 0, tzinfo=UTC)
COLL_ID = "EQChoaGhoaGhoaGhoaGhoaGhoaGhoaGhoaGhoaGhoaGhodWi"
A = TonAddress(workchain=0, raw_bytes=bytes([0xA1]) * 32)
B = TonAddress(workchain=0, raw_bytes=bytes([0xB2]) * 32)
C = TonAddress(workchain=0, raw_bytes=bytes([0xC3]) * 32)

OLD_WALLET = WalletInfo(address=A.raw_str, created_at=NOW - timedelta(days=120))


def _sale(
    idx: int,
    price: str,
    *,
    seller: TonAddress = A,
    buyer: TonAddress = B,
    hours_ago: int | None = None,
    item_id: str = "EQItem1",
) -> SaleEvent:
    return SaleEvent(
        id=f"tx-{idx}",
        item_id=item_id,
        collection_id=COLL_ID,
        price=TONAmount.from_ton(D(price)),
        buyer=buyer,
        seller=seller,
        tx_hash=f"tx-{idx}",
        sold_at=NOW - timedelta(hours=idx if hours_ago is None else hours_ago),
        marketplace=Marketplace.GETGEMS,
    )


def _healthy_sales(count: int = 20) -> tuple[SaleEvent, ...]:
    return tuple(_sale(i, str(10 + i), item_id=f"EQItem{i}") for i in range(1, count + 1))


def _input(
    *,
    collection_name: str = "Fluffy Punks",
    item_name: str = "Fluffy #1",
    known: tuple[str, ...] = ("Fluffy Punks", "Telegram Numbers"),
    item_sales: tuple[SaleEvent, ...] = (),
    coll_sales: tuple[SaleEvent, ...] | None = None,
    wallet: WalletInfo | None = OLD_WALLET,
    media: bool | None = True,
    is_auction: bool = False,
    royalty_bps: int = 0,
) -> ScreeningInput:
    item = Item(
        id="EQItem1",
        collection_id=COLL_ID,
        index=1,
        name=item_name,
        media_url="https://ipfs.io/img.png" if media is not None else None,
    )
    collection = Collection(
        id=COLL_ID,
        name=collection_name,
        slug=collection_name.lower().replace(" ", "-"),
        marketplace=Marketplace.GETGEMS,
        royalty_bps=royalty_bps,
    )
    listing = Listing(
        id="getgems:lg-1",
        external_id="lg-1",
        marketplace=Marketplace.GETGEMS,
        item=item,
        price=TONAmount.from_ton(D("50")),
        seller=A,
        listed_at=NOW,
    )
    return ScreeningInput(
        listing=listing,
        collection=collection,
        item_sales=item_sales,
        collection_sales_30d=coll_sales if coll_sales is not None else _healthy_sales(),
        seller_wallet=wallet,
        media_available=media,
        is_auction=is_auction,
        known_collection_names=known,
    )


@dataclass(frozen=True, slots=True)
class Case:
    name: str
    scam: bool
    expected: str | None
    data: ScreeningInput


def _build_dataset() -> list[Case]:
    return [
        # ── скам-кейсы ──────────────────────────────────────────────
        Case(
            "wash_round_trip",
            True,
            "WASH_TRADING",
            _input(
                item_sales=(
                    _sale(1, "50", seller=A, buyer=B, hours_ago=3),
                    _sale(2, "50", seller=B, buyer=A, hours_ago=1),
                )
            ),
        ),
        Case(
            "wash_ring",
            True,
            "WASH_TRADING",
            _input(
                item_sales=(
                    _sale(1, "50", seller=A, buyer=B, hours_ago=5),
                    _sale(2, "50", seller=B, buyer=C, hours_ago=4),
                    _sale(3, "50", seller=C, buyer=A, hours_ago=3),
                )
            ),
        ),
        Case(
            "clone_homoglyph",
            True,
            "CLONE_COLLECTION",
            _input(collection_name="Теlegram Numbers", known=("Telegram Numbers",)),
        ),
        Case(
            "clone_typo",
            True,
            "CLONE_COLLECTION",
            _input(
                collection_name="Anonymous Telegram Numbrs", known=("Anonymous Telegram Numbers",)
            ),
        ),
        Case("low_volume", True, "LOW_VOLUME", _input(coll_sales=(_sale(1, "10"), _sale(2, "11")))),
        Case("broken_metadata", True, "BROKEN_METADATA", _input(item_name="")),
        Case("media_unavailable", True, "BROKEN_METADATA", _input(media=False)),
        Case(
            "fresh_seller",
            True,
            "FRESH_SELLER",
            _input(wallet=WalletInfo(address=A.raw_str, created_at=NOW - timedelta(days=1))),
        ),
        Case("unknown_seller", True, "UNKNOWN_SELLER", _input(wallet=None)),
        Case(
            "fake_sales",
            True,
            "FAKE_SALES",
            _input(coll_sales=(*_healthy_sales(10), _sale(99, "500", item_id="EQItem99"))),
        ),
        Case("auction", True, "AUCTION_MISMATCH", _input(is_auction=True)),
        # ── чистые кейсы ────────────────────────────────────────────
        Case("clean_baseline", False, None, _input()),
        Case(
            "same_collection_not_clone",
            False,
            None,
            _input(collection_name="Telegram Numbers", known=("Telegram Numbers",)),
        ),
        Case(
            "distinct_name",
            False,
            None,
            _input(collection_name="Punk Skulls", known=("Telegram Numbers",)),
        ),
        Case("old_seller", False, None, _input(wallet=OLD_WALLET)),
        Case("high_volume", False, None, _input(coll_sales=_healthy_sales(30))),
        Case("media_ok", False, None, _input(media=True)),
        Case("normal_prices", False, None, _input(coll_sales=_healthy_sales(10))),
        Case("fixed_price", False, None, _input(is_auction=False)),
        Case("modest_royalty", False, None, _input(royalty_bps=500)),
        Case(
            "seller_age_boundary",
            False,
            None,
            _input(wallet=WalletInfo(address=A.raw_str, created_at=NOW - timedelta(days=10))),
        ),
    ]


def _caught(score: RiskScore) -> bool:
    return score.worst_severity in (RiskSeverity.MEDIUM, RiskSeverity.HIGH)


def test_scam_dataset_meets_acceptance_criteria() -> None:
    cases = _build_dataset()
    scam_cases = [case for case in cases if case.scam]
    benign_cases = [case for case in cases if not case.scam]

    caught_scam = 0
    for case in scam_cases:
        score = compute_risk(case.data, now=NOW)
        assert case.expected in {flag.code for flag in score.flags}, (
            f"{case.name}: ожидался {case.expected}, получено {[flag.code for flag in score.flags]}"
        )
        if _caught(score):
            caught_scam += 1

    false_positives = sum(1 for case in benign_cases if _caught(compute_risk(case.data, now=NOW)))

    recall = caught_scam / len(scam_cases)
    fp_rate = false_positives / len(benign_cases)

    assert recall >= D("0.9"), f"recall {recall} ниже порога 0.9"
    assert fp_rate <= D("0.1"), f"false positive rate {fp_rate} выше порога 0.1"
    assert false_positives == 0  # на подготовленном наборе чистые — действительно чистые
