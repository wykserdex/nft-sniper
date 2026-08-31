"""Initial schema: extensions.

Revision ID: 0001
Revises:
Create Date: 2026-08-31

"""
from collections.abc import Sequence

from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # pg_trgm — для будущего fuzzy-поиска названий коллекций
    # (детект клонов и unicode-подмен в risk-модуле).
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")


def downgrade() -> None:
    op.execute("DROP EXTENSION IF EXISTS pg_trgm")
