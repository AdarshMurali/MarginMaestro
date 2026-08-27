"""latest_prices

Revision ID: 914af690c86a
Revises: 7316c632b993
Create Date: 2026-08-27 09:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "914af690c86a"
down_revision: str | Sequence[str] | None = "7316c632b993"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema.

    LatestPriceORM (models.py) has existed since MM-59 but never had a
    migration generated for it -- found live running MM-102's first
    deployed /exposure request ("Invalid object name 'latest_prices'").
    Every other table this project's ORM defines already has one; this
    backfills the missing one to match.
    """
    op.create_table(
        "latest_prices",
        sa.Column("ticker", sa.String(length=20), nullable=False),
        sa.Column("price", sa.Float(), nullable=False),
        sa.Column("currency", sa.String(length=10), nullable=False),
        sa.Column("source", sa.String(length=20), nullable=False),
        sa.Column("as_of", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("ticker"),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table("latest_prices")
