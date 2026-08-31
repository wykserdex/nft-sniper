"""Таблицы ТЗ §5: collections, items, listings, sales, price_stats,
valuations, alerts, decisions, outcomes, user_settings, watchlist,
alert_registry.

Revision ID: 0002
Revises: 0001
Create Date: 2026-08-31

"""

from collections.abc import Sequence

from alembic import op

from nftsniper.infrastructure.database import models  # noqa: F401 — метадата
from nftsniper.infrastructure.database.engine import Base

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    Base.metadata.create_all(bind=op.get_bind())


def downgrade() -> None:
    Base.metadata.drop_all(bind=op.get_bind())
