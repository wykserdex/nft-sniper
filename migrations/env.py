"""Alembic env: асинхронные миграции на DSN приложения (NFT_POSTGRES_DSN)."""

import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from nftsniper.config.settings import get_settings
from nftsniper.infrastructure.database.engine import Base
from nftsniper.infrastructure.database import models  # noqa: F401  — регистрирует таблицы

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# ORM-модели зарегистрированы — autogenerate работает.
target_metadata = Base.metadata


def _dsn() -> str:
    return get_settings().postgres_dsn


def run_migrations_offline() -> None:
    """Миграции в offline-режиме (SQL в файл, без подключения)."""
    context.configure(
        url=_dsn(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        render_as_batch=True,
    )

    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    section = dict(config.get_section(config.config_ini_section, {}))
    section["sqlalchemy.url"] = _dsn()
    connectable = async_engine_from_config(
        section,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
