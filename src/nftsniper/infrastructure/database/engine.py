"""Асинхронный SQLAlchemy-движок (PostgreSQL + asyncpg)."""

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from nftsniper.config.settings import Settings


class Base(DeclarativeBase):
    """Базовый класс ORM-моделей.

    Конкретные модели появятся вместе с контекстами;
    метадату нужно будет зарегистрировать в ``migrations/env.py``
    для autogenerate.
    """


def create_database(settings: Settings) -> AsyncEngine:
    return create_async_engine(
        settings.postgres_dsn,
        pool_size=10,
        max_overflow=20,
        pool_pre_ping=True,
        pool_recycle=1800,
    )


def create_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)


async def ping_db(engine: AsyncEngine) -> None:
    """Бросает исключение, если база недоступна (для /readyz и `nftsniper check`)."""
    async with engine.connect() as conn:
        await conn.execute(text("SELECT 1"))
