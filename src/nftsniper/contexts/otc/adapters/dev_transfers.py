"""Dev-наблюдение пересылок: симулирует on-chain до появления ChainPort.

Появляется только в dev-режиме (app_env=dev) — в прод роут /dev не
регистрируется вообще. Реальная верификация: входящие переводы с
текстовым комментарием (memo) на адрес продавца через TonAPI/TonCenter.
"""

import asyncio
import secrets
from datetime import datetime

from nftsniper.contexts.otc.ports import ObservedTransfer
from nftsniper.shared.ton_address import TonAddress


class DevTransferStore:
    def __init__(self) -> None:
        self._transfers: list[ObservedTransfer] = []
        self._lock = asyncio.Lock()

    async def simulate(
        self,
        *,
        from_address: str,
        to_address: str,
        amount_nano: int,
        comment: str,
        at: datetime,
    ) -> ObservedTransfer:
        transfer = ObservedTransfer(
            from_address=from_address,
            to_address=to_address,
            amount_nano=amount_nano,
            comment=comment,
            tx_hash="dev_tx_" + secrets.token_hex(16),
            at=at,
        )
        async with self._lock:
            self._transfers.append(transfer)
        return transfer

    async def find_transfer(
        self,
        *,
        to: TonAddress,
        amount_nano: int,
        comment: str,
        since: datetime,
    ) -> ObservedTransfer | None:
        expected_to = to.user_friendly(bounceable=False)
        async with self._lock:
            for transfer in reversed(self._transfers):
                if (
                    transfer.to_address == expected_to
                    and transfer.amount_nano == amount_nano
                    and transfer.comment == comment
                    and transfer.at >= since
                ):
                    return transfer
        return None
