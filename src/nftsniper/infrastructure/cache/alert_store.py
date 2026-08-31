"""Redis-хранилище алертов: дедупликация и rate limit с TTL.

Реализует ``AlertRepository`` поверх Redis (ТЗ §9: «idempotency key и dedup
в Redis с TTL»). Ключи:

- ``alert:{id}`` — hash с полями алерта (TTL 7 дней);
- ``alerts:user:{user_id}`` — zset (score=epoch) для rate limit (TTL 25ч);
- ``alerts:dedup:{user_id}:{dedup_key}`` — zset для дедупа (TTL 7 дней);
- ``alerts:recent`` — глобальный zset для ``list_recent`` (трекинг исходов).

Оценки таймстемпов — целые секунды эпохи (int, без float: деньги и так
Decimal, а здесь точность до секунды достаточна для окон ≥ 1 часа).
"""

from __future__ import annotations

from collections.abc import Awaitable, Sequence
from datetime import UTC, datetime
from typing import cast

import redis.asyncio as aioredis

from nftsniper.contexts.alerts.domain.alert import Alert

_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
_ALERT_TTL_SECONDS = 7 * 86400
_USER_WINDOW_TTL_SECONDS = 25 * 3600
_PLUS_INF = "+inf"


async def _resolve(result: Awaitable[object] | object) -> object:
    """Сузить ``Awaitable[X] | X`` redis-py 6.x до результата.

    redis-py 6.x аннотирует async-команды как ``Awaitable[X] | X`` (общий
    базовый класс sync/async клиентов). Здесь всегда async-контекст, поэтому
    берём ``Awaitable``-ветку.
    """
    return await cast("Awaitable[object]", result)


def _epoch_seconds(ts: datetime) -> int:
    return int((ts - _EPOCH).total_seconds())


def _parse_sent_at(raw: str) -> datetime:
    return datetime.fromisoformat(raw)


def _alert_to_hash(alert: Alert) -> dict[str, str]:
    return {
        "user_id": alert.user_id,
        "listing_id": alert.listing_id,
        "valuation_id": alert.valuation_id,
        "dedup_key": alert.dedup_key,
        "sent_at": alert.sent_at.isoformat(),
        "message_id": alert.message_id if alert.message_id is not None else "",
    }


def _alert_from_hash(alert_id: str, data: dict[str, str]) -> Alert | None:
    if not data:
        return None
    message_id = data.get("message_id") or None
    return Alert(
        id=alert_id,
        user_id=data["user_id"],
        listing_id=data["listing_id"],
        valuation_id=data.get("valuation_id", ""),
        dedup_key=data["dedup_key"],
        sent_at=_parse_sent_at(data["sent_at"]),
        message_id=message_id,
    )


class RedisAlertStore:
    """AlertRepository на Redis: дедуп и rate limit через sorted sets + TTL."""

    def __init__(self, redis: aioredis.Redis) -> None:
        self._redis = redis

    async def save(self, alert: Alert) -> None:
        score = _epoch_seconds(alert.sent_at)
        pipeline = self._redis.pipeline()
        pipeline.hset(f"alert:{alert.id}", mapping=_alert_to_hash(alert))
        pipeline.expire(f"alert:{alert.id}", _ALERT_TTL_SECONDS)
        pipeline.zadd(f"alerts:user:{alert.user_id}", {alert.id: score})
        pipeline.expire(f"alerts:user:{alert.user_id}", _USER_WINDOW_TTL_SECONDS)
        pipeline.zadd(f"alerts:dedup:{alert.user_id}:{alert.dedup_key}", {alert.id: score})
        pipeline.expire(f"alerts:dedup:{alert.user_id}:{alert.dedup_key}", _ALERT_TTL_SECONDS)
        pipeline.zadd("alerts:recent", {alert.id: score})
        pipeline.expire("alerts:recent", _ALERT_TTL_SECONDS)
        await pipeline.execute()

    async def get(self, alert_id: str) -> Alert | None:
        data = cast("dict[str, str]", await _resolve(self._redis.hgetall(f"alert:{alert_id}")))
        return _alert_from_hash(alert_id, data)

    async def _ids_for(self, key: str, since_epoch: int) -> list[str]:
        return cast(
            "list[str]",
            await _resolve(self._redis.zrangebyscore(key, str(since_epoch), _PLUS_INF)),
        )

    async def list_by_user(self, user_id: str) -> Sequence[Alert]:
        ids = cast(
            "list[str]",
            await _resolve(self._redis.zrange(f"alerts:user:{user_id}", 0, -1)),
        )
        return [alert for alert_id in ids if (alert := await self.get(alert_id)) is not None]

    async def list_recent(self, since: datetime) -> Sequence[Alert]:
        ids = await self._ids_for("alerts:recent", _epoch_seconds(since))
        return [alert for alert_id in ids if (alert := await self.get(alert_id)) is not None]

    async def find_recent_by_dedup(
        self, user_id: str, dedup_key: str, since_ts: datetime
    ) -> Alert | None:
        key = f"alerts:dedup:{user_id}:{dedup_key}"
        ids = cast(
            "list[str]",
            await _resolve(
                self._redis.zrevrangebyscore(
                    key, _PLUS_INF, str(_epoch_seconds(since_ts)), start=0, num=1
                )
            ),
        )
        if not ids:
            return None
        return await self.get(ids[0])

    async def count_recent(self, user_id: str, since: datetime) -> int:
        return cast(
            int,
            await _resolve(
                self._redis.zcount(f"alerts:user:{user_id}", str(_epoch_seconds(since)), _PLUS_INF)
            ),
        )
