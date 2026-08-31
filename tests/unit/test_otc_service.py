"""OTC-сервис: создание сделки, верификация оплаты, переходы состояний."""

from datetime import UTC, datetime, timedelta

import pytest

from nftsniper.contexts.otc.adapters.inmemory_repo import InMemoryOtcDealRepository
from nftsniper.contexts.otc.adapters.sample_items import SampleItemSource
from nftsniper.contexts.otc.application.service import (
    OtcService,
    parse_buyer_address,
)
from nftsniper.contexts.otc.domain.deal import (
    ItemNotFoundError,
    OtcError,
    OtcNotFoundError,
    OtcStatus,
)
from nftsniper.contexts.otc.ports import ObservedTransfer
from nftsniper.shared.ton_address import TonAddress, TonAddressError

T0 = datetime(2026, 8, 31, 12, 0, 0, tzinfo=UTC)
BUYER = TonAddress(workchain=0, raw_bytes=bytes([0x42]) * 32)


class Clock:
    def __init__(self, t: datetime) -> None:
        self.t = t

    def __call__(self) -> datetime:
        return self.t


class FakeTransfers:
    def __init__(self) -> None:
        self.queue: list[ObservedTransfer] = []

    def add(self, **kwargs: object) -> None:
        self.queue.append(ObservedTransfer(**kwargs))  # type: ignore[arg-type]

    async def find_transfer(
        self,
        *,
        to: TonAddress,
        amount_nano: int,
        comment: str,
        since: datetime,
    ) -> ObservedTransfer | None:
        for transfer in reversed(self.queue):
            if (
                transfer.to_address == to.user_friendly(bounceable=False)
                and transfer.amount_nano == amount_nano
                and transfer.comment == comment
                and transfer.at >= since
            ):
                return transfer
        return None


Env = tuple[OtcService, FakeTransfers, Clock]


class FakeQr:
    def make(self, data: str) -> str:
        return "data:image/png;base64,FAKE"


@pytest.fixture
def env() -> tuple[OtcService, FakeTransfers, Clock]:
    clock = Clock(T0)
    transfers = FakeTransfers()
    service = OtcService(
        SampleItemSource(),
        InMemoryOtcDealRepository(),
        transfers,
        FakeQr(),
        ttl=timedelta(minutes=30),
        now=clock,
    )
    return service, transfers, clock


def _seller_888() -> TonAddress:
    """Тот же синтетический продавец, что в SampleItemSource (0x88 * 32)."""
    return TonAddress(workchain=0, raw_bytes=bytes([0x88]) * 32)


async def test_create_deal(env: Env) -> None:
    service, _, clock = env
    deal = await service.create_deal("anon-888", BUYER.user_friendly())
    assert deal.id.startswith("OTC-")
    assert deal.comment == deal.id
    assert deal.status is OtcStatus.AWAITING_PAYMENT
    assert deal.amount_nano == 120_000_000_000
    assert deal.expires_at == T0 + timedelta(minutes=30)
    assert deal.created_at == T0
    _ = clock


async def test_create_unknown_item(env: Env) -> None:
    service, _, _ = env
    with pytest.raises(ItemNotFoundError):
        await service.create_deal("nope", BUYER.user_friendly())


async def test_create_bad_buyer_address(env: Env) -> None:
    service, _, _ = env
    with pytest.raises(TonAddressError):
        await service.create_deal("anon-888", "UQ-garbage")
    with pytest.raises(TonAddressError):
        await service.create_deal("anon-888", "0:0000000000000000000000000000000000000000")


async def test_parse_buyer_address() -> None:
    assert parse_buyer_address(BUYER.user_friendly()) == BUYER


async def test_check_payment_no_transfer(env: Env) -> None:
    service, _, _ = env
    deal = await service.create_deal("anon-888", BUYER.user_friendly())
    checked = await service.check_payment(deal.id)
    assert checked.status is OtcStatus.AWAITING_PAYMENT


async def test_check_payment_found(env: Env) -> None:
    service, transfers, _ = env
    deal = await service.create_deal("anon-888", BUYER.user_friendly())
    seller = _seller_888()
    transfers.add(
        from_address=BUYER.user_friendly(),
        to_address=seller.user_friendly(bounceable=False),
        amount_nano=deal.amount_nano,
        comment=deal.comment,
        tx_hash="tx_abc",
        at=T0 + timedelta(minutes=1),
    )
    checked = await service.check_payment(deal.id)
    assert checked.status is OtcStatus.PAID
    assert checked.paid_tx_hash == "tx_abc"


async def test_check_payment_wrong_amount_ignored(env: Env) -> None:
    service, transfers, _ = env
    deal = await service.create_deal("anon-888", BUYER.user_friendly())
    seller = _seller_888()
    transfers.add(
        from_address=BUYER.user_friendly(),
        to_address=seller.user_friendly(bounceable=False),
        amount_nano=deal.amount_nano - 1,
        comment=deal.comment,
        tx_hash="tx_wrong",
        at=T0 + timedelta(minutes=1),
    )
    checked = await service.check_payment(deal.id)
    assert checked.status is OtcStatus.AWAITING_PAYMENT


async def test_check_payment_wrong_comment_ignored(env: Env) -> None:
    service, transfers, _ = env
    deal = await service.create_deal("anon-888", BUYER.user_friendly())
    seller = _seller_888()
    transfers.add(
        from_address=BUYER.user_friendly(),
        to_address=seller.user_friendly(bounceable=False),
        amount_nano=deal.amount_nano,
        comment="OTC-OTHER",
        tx_hash="tx_other",
        at=T0 + timedelta(minutes=1),
    )
    checked = await service.check_payment(deal.id)
    assert checked.status is OtcStatus.AWAITING_PAYMENT


async def test_expiry_after_ttl(env: Env) -> None:
    service, _, clock = env
    deal = await service.create_deal("anon-888", BUYER.user_friendly())
    clock.t = T0 + timedelta(minutes=31)
    checked = await service.check_payment(deal.id)
    assert checked.status is OtcStatus.EXPIRED
    with pytest.raises(OtcError):
        await service.confirm_nft_received(deal.id)


async def test_cancel(env: Env) -> None:
    service, _, _ = env
    deal = await service.create_deal("anon-888", BUYER.user_friendly())
    cancelled = await service.cancel_deal(deal.id)
    assert cancelled.status is OtcStatus.CANCELLED
    with pytest.raises(OtcError):
        await service.cancel_deal(deal.id)


async def test_confirm_nft_from_awaiting_rejected(env: Env) -> None:
    service, _, _ = env
    deal = await service.create_deal("anon-888", BUYER.user_friendly())
    with pytest.raises(OtcError):
        await service.confirm_nft_received(deal.id)


async def test_full_happy_path(env: Env) -> None:
    service, transfers, _ = env
    deal = await service.create_deal("anon-888", BUYER.user_friendly())
    seller = _seller_888()
    transfers.add(
        from_address=BUYER.user_friendly(),
        to_address=seller.user_friendly(bounceable=False),
        amount_nano=deal.amount_nano,
        comment=deal.comment,
        tx_hash="tx_pay",
        at=T0 + timedelta(minutes=2),
    )
    paid = await service.check_payment(deal.id)
    assert paid.status is OtcStatus.PAID
    done = await service.confirm_nft_received(deal.id, "tx_nft")
    assert done.status is OtcStatus.COMPLETED
    assert done.nft_tx_hash == "tx_nft"


async def test_payload_fields(env: Env) -> None:
    service, _, _ = env
    deal = await service.create_deal("anon-888", BUYER.user_friendly())
    payload = service.payload(deal)
    assert payload.amount_ton == "120"
    assert payload.amount_nano == "120000000000"
    assert payload.comment == deal.id
    assert payload.qr_data_uri == "data:image/png;base64,FAKE"
    assert payload.tonkeeper_url.startswith("tonkeeper://transfer/")
    assert payload.universal_link.startswith("https://app.tonkeeper.com/transfer/")
    assert (
        payload.qr_url
        == f"ton://transfer/{payload.seller_address}?amount=120000000000&text={deal.id}"
    )


async def test_get_deal_missing(env: Env) -> None:
    service, _, _ = env
    with pytest.raises(OtcNotFoundError):
        await service.get_deal("OTC-NOPE1")
