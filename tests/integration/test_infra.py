"""Интеграционные тесты: реальный Postgres + Redis + alembic.

В CI запускаются на сервисах GitHub Actions (см. .github/workflows/ci.yml).
Локально: `docker compose up -d postgres redis && make test-integration`.
Без поднятых сервисов тесты сами промаркируются как skipped.
"""

import asyncio

import pytest
from alembic import command
from alembic.config import Config

from nftsniper.config.settings import Settings
from nftsniper.infrastructure.cache.redis import create_redis, ping_redis
from nftsniper.infrastructure.database.engine import create_database, ping_db


def _settings() -> Settings:
    return Settings(_env_file=None)


async def _probe_infra() -> bool:
    settings = _settings()
    engine = create_database(settings)
    try:
        await ping_db(engine)
    except Exception:
        await engine.dispose()
        return False
    await engine.dispose()

    pool = create_redis(settings)
    try:
        await ping_redis(pool)
    except Exception:
        await pool.aclose()
        return False
    await pool.aclose()
    return True


@pytest.fixture(scope="module", autouse=True)
def _require_infra() -> None:
    if not asyncio.run(_probe_infra()):
        pytest.skip("Postgres/Redis недоступны (docker compose up -d postgres redis)")


async def test_database_ping() -> None:
    engine = create_database(_settings())
    try:
        await ping_db(engine)
    finally:
        await engine.dispose()


async def test_redis_ping() -> None:
    pool = create_redis(_settings())
    try:
        await ping_redis(pool)
    finally:
        await pool.aclose()


def test_alembic_upgrade_head() -> None:
    cfg = Config("alembic.ini")
    command.upgrade(cfg, "head")

    # Схему можно свободно мигрировать в обе стороны
    command.downgrade(cfg, "base")
    command.upgrade(cfg, "head")
