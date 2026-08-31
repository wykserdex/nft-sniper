"""Коллекция NFT."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from nftsniper.contexts.sources.domain.marketplace import Marketplace
from nftsniper.shared.domain.base import Entity


@dataclass(frozen=True, slots=True)
class Collection(Entity):
    """Коллекция. ``id`` — on-chain-адрес контракта коллекции.

    ``risk_score`` (0..1, None = не оценивалась) — из risk-контекста;
    храним как Decimal, чтобы не создавать зависимость contexts → contexts.
    ``royalty_bps`` — роялти коллекции в базисных пунктах (1/10000),
    для учёта в реальном выходе (ТЗ §4).
    """

    id: str
    name: str
    slug: str
    marketplace: Marketplace | None = None
    verified: bool = False
    created_at: datetime | None = None
    items_count: int = 0
    royalty_bps: int = 0
    risk_score: Decimal | None = None

    def with_risk_score(self, score: Decimal) -> Collection:
        return Collection(
            id=self.id,
            name=self.name,
            slug=self.slug,
            marketplace=self.marketplace,
            verified=self.verified,
            created_at=self.created_at,
            items_count=self.items_count,
            royalty_bps=self.royalty_bps,
            risk_score=score,
        )
