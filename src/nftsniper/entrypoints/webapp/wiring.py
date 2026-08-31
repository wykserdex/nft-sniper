"""Сборка зависимостей мини-аппа из настроек."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from nftsniper.config.settings import Settings
from nftsniper.contexts.otc.adapters.dev_transfers import DevTransferStore
from nftsniper.contexts.otc.adapters.inmemory_repo import InMemoryOtcDealRepository
from nftsniper.contexts.otc.adapters.sample_items import SampleItemSource
from nftsniper.contexts.otc.adapters.segno_qr import SegnoQr
from nftsniper.contexts.otc.application.service import OtcService
from nftsniper.contexts.otc.ports import ObservedTransfer
from nftsniper.shared.ton_address import TonAddress

from .api import WEBAPP_STATIC


class NoopTransferObservation:
    """Пока ChainPort не готов: пересылки не наблюдаются.

    Верификация оплаты появится вместе с on-chain адаптером — до этого
    dev-режим симулирует пересылки через /api/webapp/dev/transfer.
    """

    async def find_transfer(
        self,
        *,
        to: TonAddress,
        amount_nano: int,
        comment: str,
        since: datetime,
    ) -> ObservedTransfer | None:
        return None


@dataclass(frozen=True, slots=True)
class WebappDeps:
    service: OtcService
    dev_transfers: DevTransferStore | None
    static_dir: Path


def create_webapp_deps(settings: Settings) -> WebappDeps:
    dev_transfers = DevTransferStore() if settings.app_env == "dev" else None
    service = OtcService(
        items=SampleItemSource(),
        deals=InMemoryOtcDealRepository(),
        transfers=dev_transfers if dev_transfers is not None else NoopTransferObservation(),
        qr=SegnoQr(),
        ttl=timedelta(minutes=settings.otc_ttl_minutes),
    )
    return WebappDeps(
        service=service,
        dev_transfers=dev_transfers,
        static_dir=WEBAPP_STATIC,
    )
