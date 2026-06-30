"""add instruments.followed flag

Revision ID: 20260625_06
Revises: 20260623_05
Create Date: 2026-06-25 16:00:00
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "20260625_06"
down_revision: str | None = "20260623_05"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    # Soft "followed" flag: existing instruments default to followed so they keep
    # showing in the quick-access list after the migration.
    op.add_column(
        "instruments",
        sa.Column("followed", sa.Boolean(), nullable=False, server_default=sa.true()),
    )


def downgrade() -> None:
    op.drop_column("instruments", "followed")
