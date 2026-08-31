"""Нормализация сырых ответов TonAPI → доменные модели.

Чистые функции без I/O и без float. Схема TonAPI (REST v2, ``/v2/nfts/…``,
``/v2/accounts/…``) версионируется, поэтому чтение полей защитное: битая
запись пропускается, а не роняет всю пачку.

Ключевые формы ответов (закреплены фикстурами ``tests/fixtures/tonapi/*.json``):

- ``NftItem`` (``GET /v2/nfts/{id}``) → ``owner.address`` (raw ``0:hex``).
- ``AccountEvents`` (``GET /v2/nfts/{id}/history``, ``GET /v2/accounts/{id}/events``)
  → ``events[]``; внутри каждого события ``actions[]`` с типом и вложенным
  объектом, названным по типу: ``NftItemTransfer`` (sender/recipient/nft) и
  ``TonTransfer`` (sender/recipient/amount в nanoTON). ``tx_hash`` берётся из
  ``event_id`` события, сумма продажи — максимальный ``TonTransfer.amount``
  в том же событии.
- ``Account`` (``GET /v2/accounts/{id}``) → ``status`` (``nonexist``/``uninit``/
  ``active``), ``last_activity``, ``is_wallet``.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from nftsniper.contexts.sources.domain.chain import NftTransfer, WalletInfo
from nftsniper.shared.money import TONAmount
from nftsniper.shared.ton_address import TonAddress, TonAddressError

_ACTION_NFT_TRANSFER = "NftItemTransfer"
_ACTION_TON_TRANSFER = "TonTransfer"


def _text(value: Any) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _int(value: Any) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        try:
            return int(value.strip())
        except ValueError:
            return None
    return None


def _unix_to_utc(value: Any) -> datetime | None:
    seconds = _int(value)
    if seconds is None:
        return None
    return datetime.fromtimestamp(seconds, tz=UTC)


def raw_to_user_friendly(address: str | None) -> str | None:
    """Raw ``0:hex`` → user-friendly ``UQ…`` (non-bounceable, с чек-суммой)."""
    if address is None:
        return None
    try:
        return TonAddress.from_raw(address).user_friendly()
    except (TonAddressError, ValueError):
        return None


def parse_nft_owner(node: dict[str, Any]) -> str | None:
    """``NftItem`` → user-friendly адрес владельца; None, если владельца нет."""
    owner = node.get("owner")
    if not isinstance(owner, dict):
        return None
    return raw_to_user_friendly(_text(owner.get("address")))


def _account_address(payload: dict[str, Any], key: str) -> str | None:
    """``payload[key]`` вида ``AccountAddress`` → raw адрес ``0:hex``."""
    holder = payload.get(key)
    if not isinstance(holder, dict):
        return None
    return _text(holder.get("address"))


def _split_actions(actions: Any) -> tuple[dict[str, Any] | None, list[int]]:
    """Из действий события: NFT-трансфер и суммы ``TonTransfer`` (nanoTON)."""
    nft_action: dict[str, Any] | None = None
    ton_amounts: list[int] = []
    if not isinstance(actions, list):
        return nft_action, ton_amounts
    for action in actions:
        if not isinstance(action, dict):
            continue
        action_type = action.get("type")
        if action_type == _ACTION_NFT_TRANSFER and nft_action is None:
            payload = action.get(_ACTION_NFT_TRANSFER)
            if isinstance(payload, dict):
                nft_action = payload
        elif action_type == _ACTION_TON_TRANSFER:
            payload = action.get(_ACTION_TON_TRANSFER)
            if isinstance(payload, dict):
                amount = _int(payload.get("amount"))
                if amount is not None and amount >= 0:
                    ton_amounts.append(amount)
    return nft_action, ton_amounts


def _parse_event(event: Any, nft_address: str) -> NftTransfer | None:
    if not isinstance(event, dict):
        return None
    timestamp = _unix_to_utc(event.get("timestamp"))
    if timestamp is None:
        return None
    nft_action, ton_amounts = _split_actions(event.get("actions"))
    if nft_action is None:
        return None
    from_address = _account_address(nft_action, "sender")
    to_address = _account_address(nft_action, "recipient")
    if from_address is None or to_address is None:
        return None
    amount_nano = max(ton_amounts) if ton_amounts else None
    return NftTransfer(
        tx_hash=_text(event.get("event_id")) or "",
        nft_address=_text(nft_action.get("nft")) or nft_address,
        from_address=from_address,
        to_address=to_address,
        timestamp=timestamp,
        amount=TONAmount.from_nano(amount_nano) if amount_nano is not None else None,
    )


def parse_transfers(events: Any, *, nft_address: str) -> list[NftTransfer]:
    """``AccountEvents.events`` → список ``NftTransfer`` (защитное чтение).

    Событие без ``NftItemTransfer``-действия пропускается; если в событии есть
    ``TonTransfer``-действия, суммой продажи считается максимальный ``amount``
    (в nanoTON) — у sale-контракта это доминирующий перевод.
    """
    transfers: list[NftTransfer] = []
    if not isinstance(events, list):
        return transfers
    for event in events:
        transfer = _parse_event(event, nft_address)
        if transfer is not None:
            transfers.append(transfer)
    return transfers


def parse_wallet(
    account: dict[str, Any],
    *,
    first_event_timestamp: int | None,
    total_inflow_nano: int,
) -> WalletInfo | None:
    """``Account`` + производные → ``WalletInfo``. None, если нет адреса."""
    address = _text(account.get("address"))
    if address is None:
        return None
    created_at = _unix_to_utc(first_event_timestamp)
    total_inflow = TONAmount.from_nano(total_inflow_nano) if total_inflow_nano > 0 else None
    return WalletInfo(address=address, created_at=created_at, total_inflow=total_inflow)


def parse_first_event_timestamp(events: Any) -> int | None:
    """Время первого события (``sort_order=asc&limit=1``) → возраст кошелька."""
    if not isinstance(events, dict):
        return None
    items = events.get("events")
    if not isinstance(items, list) or not items:
        return None
    first = items[0]
    if not isinstance(first, dict):
        return None
    return _int(first.get("timestamp"))


def sum_inbound_nano(events: Any, *, wallet_address: str) -> int:
    """Сумма входящих ``TonTransfer`` (nanoTON) для кошелька за окно событий."""
    if not isinstance(events, dict):
        return 0
    items = events.get("events")
    if not isinstance(items, list):
        return 0
    total = 0
    for event in items:
        if not isinstance(event, dict):
            continue
        for action in event.get("actions", []) if isinstance(event.get("actions"), list) else []:
            if not isinstance(action, dict) or action.get("type") != _ACTION_TON_TRANSFER:
                continue
            payload = action.get(_ACTION_TON_TRANSFER)
            if not isinstance(payload, dict):
                continue
            recipient = payload.get("recipient")
            recipient_address = recipient.get("address") if isinstance(recipient, dict) else None
            if _text(recipient_address) != wallet_address:
                continue
            amount = _int(payload.get("amount"))
            if amount is not None and amount > 0:
                total += amount
    return total
