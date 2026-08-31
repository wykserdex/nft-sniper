"""Юнит-тесты нормализатора TonAPI — чистые функции без I/O."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from nftsniper.contexts.sources.adapters.tonapi.normalizer import (
    parse_first_event_timestamp,
    parse_nft_owner,
    parse_transfers,
    parse_wallet,
    raw_to_user_friendly,
    sum_inbound_nano,
)
from nftsniper.shared.money import TONAmount

NFT = "0:30ed366b91e98c93f9323aabfd8a97947d7b4524e28ccfb5d202f24abeee55c3"
SELLER = "0:1111111111111111111111111111111111111111111111111111111111111111"
BUYER = "0:2222222222222222222222222222222222222222222222222222222222222222"


def _event(event_id: str, ts: int, *, amount: int | None) -> dict[str, Any]:
    actions: list[dict[str, Any]] = [
        {
            "type": "NftItemTransfer",
            "status": "ok",
            "NftItemTransfer": {
                "sender": {"address": SELLER, "is_scam": False, "is_wallet": True},
                "recipient": {"address": BUYER, "is_scam": False, "is_wallet": True},
                "nft": NFT,
            },
        }
    ]
    if amount is not None:
        actions.append(
            {
                "type": "TonTransfer",
                "status": "ok",
                "TonTransfer": {
                    "sender": {"address": BUYER},
                    "recipient": {"address": SELLER},
                    "amount": amount,
                },
            }
        )
    return {"event_id": event_id, "timestamp": ts, "actions": actions}


def test_raw_to_user_friendly() -> None:
    user_friendly = raw_to_user_friendly(NFT)
    assert user_friendly is not None
    assert user_friendly.startswith("UQ")  # non-bounceable + checksum
    assert raw_to_user_friendly("not-an-address") is None
    assert raw_to_user_friendly(None) is None


def test_parse_nft_owner_returns_user_friendly() -> None:
    owner_raw = "0:759ade469adc736e3a96eb5201092738437855b6817472578e9f5bc76b5cb5d6"
    owner = parse_nft_owner({"owner": {"address": owner_raw, "is_wallet": True}})
    assert owner is not None
    assert owner.startswith("UQ")
    assert parse_nft_owner({}) is None
    assert parse_nft_owner({"owner": None}) is None


def test_parse_transfers_extracts_amounts() -> None:
    events = [
        _event("sale1", 1753000000, amount=10_000_000_000),
        _event("gift", 1753003600, amount=None),
    ]
    transfers = parse_transfers(events, nft_address=NFT)
    assert len(transfers) == 2
    sale, gift = transfers
    assert sale.tx_hash == "sale1"
    assert sale.from_address == SELLER
    assert sale.to_address == BUYER
    assert sale.amount == TONAmount.from_ton(10)
    assert sale.timestamp == datetime.fromtimestamp(1753000000, tz=UTC)
    assert gift.amount is None


def test_parse_transfers_picks_max_ton_amount_in_event() -> None:
    event = _event("sale", 1753000000, amount=5_000_000_000)
    event["actions"].append(
        {
            "type": "TonTransfer",
            "status": "ok",
            "TonTransfer": {
                "sender": {"address": BUYER},
                "recipient": {"address": "0:other"},
                "amount": 100_000_000,  # комиссия — меньше цены
            },
        }
    )
    transfers = parse_transfers([event], nft_address=NFT)
    assert len(transfers) == 1
    assert transfers[0].amount == TONAmount.from_ton(5)


def test_parse_transfers_skips_broken_events() -> None:
    events: list[object] = [
        "not a dict",
        {"event_id": "no-actions"},
        {"timestamp": 1753000000, "actions": [{"type": "Unknown"}]},
        _event("ok", 1753000000, amount=1_000_000_000),
    ]
    transfers = parse_transfers(events, nft_address=NFT)
    assert [t.tx_hash for t in transfers] == ["ok"]


def test_parse_wallet() -> None:
    account = {"address": BUYER, "status": "active"}
    wallet = parse_wallet(
        account,
        first_event_timestamp=1700000000,
        total_inflow_nano=1_500_000_000,
    )
    assert wallet is not None
    assert wallet.created_at == datetime.fromtimestamp(1700000000, tz=UTC)
    assert wallet.total_inflow == TONAmount.from_ton(Decimal("1.5"))
    assert parse_wallet({}, first_event_timestamp=None, total_inflow_nano=0) is None


def test_parse_first_event_timestamp() -> None:
    payload = {"events": [{"timestamp": 1700000000}], "next_from": 0}
    assert parse_first_event_timestamp(payload) == 1700000000
    assert parse_first_event_timestamp({"events": []}) is None
    assert parse_first_event_timestamp("bad") is None


def test_sum_inbound_nano_only_counts_incoming() -> None:
    wallet = BUYER
    events = {
        "events": [
            {
                "actions": [
                    {
                        "type": "TonTransfer",
                        "TonTransfer": {
                            "sender": {"address": "0:a"},
                            "recipient": {"address": wallet},
                            "amount": 260_000_000,
                        },
                    }
                ]
            },
            {
                "actions": [
                    {
                        "type": "TonTransfer",
                        "TonTransfer": {
                            "sender": {"address": wallet},
                            "recipient": {"address": "0:b"},
                            "amount": 6_000_000,
                        },
                    }
                ]
            },
            {
                "actions": [
                    {
                        "type": "TonTransfer",
                        "TonTransfer": {
                            "sender": {"address": "0:c"},
                            "recipient": {"address": wallet},
                            "amount": 1_500_000_000,
                        },
                    }
                ]
            },
            {
                "actions": [
                    {
                        "type": "NftItemTransfer",
                        "NftItemTransfer": {
                            "sender": {"address": "0:d"},
                            "recipient": {"address": wallet},
                        },
                    }
                ]
            },
        ]
    }
    assert sum_inbound_nano(events, wallet_address=wallet) == 1_760_000_000
