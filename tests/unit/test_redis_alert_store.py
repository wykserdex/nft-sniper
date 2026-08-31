"""RedisAlertStore: дедуп и rate limit с TTL (на fakeredis)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fakeredis.aioredis import FakeRedis

from nftsniper.contexts.alerts.domain.alert import Alert
from nftsniper.infrastructure.cache.alert_store import RedisAlertStore

NOW = datetime(2026, 8, 31, 12, 0, 0, tzinfo=UTC)


@pytest.fixture
def store() -> RedisAlertStore:
    redis = FakeRedis(decode_responses=True)
    return RedisAlertStore(redis)


def _alert(
    alert_id: str,
    user: str = "u1",
    dedup_key: str = "getgems:lg-1",
    sent_at: datetime = NOW,
    message_id: str | None = None,
) -> Alert:
    return Alert(
        id=alert_id,
        user_id=user,
        listing_id=dedup_key.partition(":")[2],
        valuation_id="v-1",
        dedup_key=dedup_key,
        sent_at=sent_at,
        message_id=message_id,
    )


async def test_save_and_get_roundtrip(store: RedisAlertStore) -> None:
    await store.save(_alert("al-1", message_id="tg-42"))
    restored = await store.get("al-1")
    assert restored is not None
    assert restored.id == "al-1"
    assert restored.user_id == "u1"
    assert restored.dedup_key == "getgems:lg-1"
    assert restored.sent_at == NOW
    assert restored.message_id == "tg-42"


async def test_find_recent_by_dedup_within_window(store: RedisAlertStore) -> None:
    await store.save(_alert("al-1", sent_at=NOW - timedelta(hours=2)))
    # Дедуп-окно 6 часов → находит.
    found = await store.find_recent_by_dedup("u1", "getgems:lg-1", NOW - timedelta(hours=6))
    assert found is not None
    assert found.id == "al-1"
    # Окно 1 час → нет (алерт старше).
    missing = await store.find_recent_by_dedup("u1", "getgems:lg-1", NOW - timedelta(hours=1))
    assert missing is None


async def test_count_recent(store: RedisAlertStore) -> None:
    await store.save(_alert("al-1", sent_at=NOW - timedelta(minutes=5)))
    await store.save(_alert("al-2", sent_at=NOW - timedelta(minutes=10)))
    await store.save(_alert("al-3", user="u2", sent_at=NOW - timedelta(minutes=1)))
    assert await store.count_recent("u1", NOW - timedelta(hours=1)) == 2
    assert await store.count_recent("u1", NOW - timedelta(minutes=7)) == 1
    assert await store.count_recent("u2", NOW - timedelta(hours=1)) == 1


async def test_list_by_user_and_recent(store: RedisAlertStore) -> None:
    await store.save(_alert("al-1", sent_at=NOW - timedelta(hours=2)))
    await store.save(_alert("al-2", dedup_key="getgems:lg-2", sent_at=NOW - timedelta(days=1)))
    await store.save(_alert("al-3", user="u2", sent_at=NOW - timedelta(hours=3)))

    by_user = await store.list_by_user("u1")
    assert {alert.id for alert in by_user} == {"al-1", "al-2"}

    recent = await store.list_recent(NOW - timedelta(hours=5))
    assert {alert.id for alert in recent} == {"al-1", "al-3"}
