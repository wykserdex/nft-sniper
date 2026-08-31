"""VerifySales: детерминированная выборка и сверка с on-chain.

Критерий готовности: «on-chain цена совпадает с API-ценой на выборке из 100
сделок, расхождения помечены» — проверяется на fake ChainPort без сети.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from nftsniper.contexts.sources.application.verify_sales import (
    DEFAULT_SAMPLE_SIZE,
    VerifySales,
    deterministic_sample,
)
from nftsniper.contexts.sources.domain.chain import SaleVerification
from nftsniper.contexts.sources.domain.sale import SaleEvent
from nftsniper.shared.money import TONAmount
from nftsniper.shared.ton_address import parse_address
from tests.fakes import FakeChainPort

SELLER = parse_address("0:1111111111111111111111111111111111111111111111111111111111111111")
BUYER = parse_address("0:2222222222222222222222222222222222222222222222222222222222222222")
SOLD_AT = datetime.fromtimestamp(1753000000, tz=UTC)


def make_sale(index: int, *, price: str, item_id: str | None = None) -> SaleEvent:
    return SaleEvent(
        id=f"sale-{index:04d}",
        item_id=item_id or f"0:{index:064x}",
        collection_id="0:coll",
        price=TONAmount.from_ton(Decimal(price)),
        buyer=BUYER,
        seller=SELLER,
        tx_hash=f"tx-{index}",
        sold_at=SOLD_AT,
    )


def test_deterministic_sample_returns_all_when_small() -> None:
    sales = [make_sale(i, price="1") for i in range(7)]
    sample = deterministic_sample(sales, 100)
    assert sample == sales


def test_deterministic_sample_is_even_and_exact() -> None:
    sales = [make_sale(i, price="1") for i in range(250)]
    sample = deterministic_sample(sales, 100)
    assert len(sample) == 100
    assert len({sale.id for sale in sample}) == 100  # без повторов
    ids = [sale.id for sale in sales]
    assert sample[0].id == ids[0]  # покрывает начало…
    assert sample[-1].id == ids[-1]  # …и конец диапазона


def test_deterministic_sample_zero_size() -> None:
    assert deterministic_sample([make_sale(0, price="1")], 0) == []


async def test_verify_sales_sample_of_100_flags_mismatches() -> None:
    """ТЗ §7: выборка из 100 сделок, 98 сходятся, 2 помечены."""
    sales = [make_sale(i, price="10") for i in range(100)]

    def verifier(sale: SaleEvent) -> SaleVerification:
        # продажи #7 и #42 «ошибаются» на 2% — помечаются
        if sale.id in {"sale-0007", "sale-0042"}:
            return SaleVerification(
                sale_id=sale.id,
                marketplace_amount=sale.price,
                on_chain_amount=TONAmount.from_ton(Decimal("9.8")),
                discrepancy=Decimal("0.02"),
                matches=False,
                reason="price_mismatch",
            )
        return SaleVerification(
            sale_id=sale.id,
            marketplace_amount=sale.price,
            on_chain_amount=sale.price,
            discrepancy=Decimal("0"),
            matches=True,
        )

    chain = FakeChainPort(verifier=verifier)
    result = await VerifySales(chain).run(sales)
    assert result.checked_count == DEFAULT_SAMPLE_SIZE
    assert result.mismatch_count == 2
    assert [verification.sale_id for verification in result.mismatches] == [
        "sale-0007",
        "sale-0042",
    ]
    assert len(chain.verify_calls) == 1
    assert len(chain.verify_calls[0]) == 100


async def test_verify_sales_delegates_to_port() -> None:
    chain = FakeChainPort()
    await VerifySales(chain).run([make_sale(0, price="1")])
    assert chain.verify_calls == [[make_sale(0, price="1")]]
