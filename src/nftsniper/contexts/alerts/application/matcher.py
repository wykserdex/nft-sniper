"""Матчинг листинга с настройками подписчика.

Чистые функции без I/O: ``match_listing`` проверяет пороги ``AlertPolicy``,
паузу и quiet hours, и собирает ``AlertCandidate``. Дедупликацию, rate limit
и доставку делает движок (``engine.py``) через порты.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from nftsniper.contexts.alerts.domain.candidate import (
    AlertCandidate,
    ListingScore,
    Subscriber,
)

_SECONDS_PER_DAY = 86400


@dataclass(frozen=True, slots=True)
class MatchOutcome:
    """Итог матчинга: пропустить (с причиной) или собрать кандидата."""

    allowed: bool
    candidate: AlertCandidate | None = None
    reason: str | None = None  # paused | quiet | rejected
    details: tuple[str, ...] = ()


def candidate_priority(*, discount: Decimal, confidence: Decimal) -> Decimal:
    """Приоритет сделки (ТЗ §7: при потоке сначала уходят лучшие).

    Дискаунт — главный фактор (×10), уверенность — тай-брейк. Монотонно по
    каждому фактору, только Decimal → детерминированно.
    """
    return discount * 10 + confidence


def _listing_age_seconds(listed_at: datetime | None, now: datetime) -> int:
    if listed_at is None:
        return 0
    delta = now - listed_at
    return max(0, delta.days * _SECONDS_PER_DAY + delta.seconds)


def match_listing(
    score: ListingScore,
    subscriber: Subscriber,
    *,
    now: datetime,
    alert_id: str,
) -> MatchOutcome:
    """Проверить листинг против подписчика и собрать кандидата (без I/O)."""
    if subscriber.paused:
        return MatchOutcome(allowed=False, reason="paused")
    policy = subscriber.policy
    if policy.is_quiet(now):
        return MatchOutcome(allowed=False, reason="quiet")

    allowed, reasons = policy.allows(
        discount=score.discount,
        confidence=score.confidence,
        price=score.listing.price,
        liquidity=score.liquidity,
        risk=score.risk_value,
    )
    if not allowed:
        return MatchOutcome(allowed=False, reason="rejected", details=reasons)

    listing = score.listing
    item = listing.item
    candidate = AlertCandidate(
        alert_id=alert_id,
        user_id=subscriber.user_id,
        language=subscriber.language,
        listing_id=listing.id,
        dedup_key=listing.dedup_key,
        item_id=item.id,
        item_name=item.name,
        collection_id=item.collection_id,
        collection_name=score.collection_name,
        price=listing.price,
        fair_price=score.fair_price,
        discount=score.discount.value,
        confidence=score.confidence,
        floor_p5=score.floor_p5,
        median_7d=score.median_7d,
        sales_7d=score.sales_7d,
        floor_24h_change=score.floor_24h_change,
        liquidity_spd=score.liquidity,
        listing_age_seconds=_listing_age_seconds(listing.listed_at, now),
        priority=candidate_priority(discount=score.discount.value, confidence=score.confidence),
        rarity_rank=item.rarity_rank,
        risk_flags=score.risk_flags,
        valuation_id=score.valuation_id,
        getgems_url=score.getgems_url,
    )
    return MatchOutcome(allowed=True, candidate=candidate)
