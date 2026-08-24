"""maintenance config -- standalone kill-switch table, separate from app_versions

Revision ID: 0047_maintenance_config
Revises: 0046_backfill_player_statistics
Create Date: 2026-08-24

New, independent table for the maintenance kill-switch. Deliberately not
a column on app_versions: maintenance ("take the whole app offline right
now") and force-update ("you're on an old version") are different
concerns with different lifecycles, and mixing them into one table made
the admin flow confusing and risked one feature's toggle interfering with
the other's config.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0047_maintenance_config"
down_revision: Union[str, None] = "0046_backfill_player_statistics"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "maintenance_config",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "is_enabled", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
        sa.Column(
            "title",
            sa.String(150),
            nullable=False,
            server_default="Under Maintenance",
        ),
        sa.Column(
            "message",
            sa.Text(),
            nullable=False,
            server_default="ClassyBattle is currently undergoing scheduled maintenance. Please check back shortly.",
        ),
        sa.Column(
            "status_url",
            sa.String(500),
            nullable=False,
            server_default="https://status.classybattle.online",
        ),
    )


def downgrade() -> None:
    op.drop_table("maintenance_config")
