"""add broker connections

Revision ID: 20260622_04
Revises: 20260622_03
Create Date: 2026-06-22 21:35:00
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "20260622_04"
down_revision: str | None = "20260622_03"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "broker_connections",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("owner_user_id", sa.Integer(), nullable=False),
        sa.Column("broker_name", sa.String(length=64), nullable=False),
        sa.Column("account_label", sa.String(length=128), nullable=False),
        sa.Column("environment", sa.String(length=16), nullable=False, server_default=sa.text("'paper'")),
        sa.Column("connection_metadata", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["owner_user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "owner_user_id",
            "broker_name",
            "account_label",
            name="uq_broker_connections_owner_broker_label",
        ),
    )
    op.create_index("ix_broker_connections_owner_user_id", "broker_connections", ["owner_user_id"])


def downgrade() -> None:
    op.drop_index("ix_broker_connections_owner_user_id", table_name="broker_connections")
    op.drop_table("broker_connections")
