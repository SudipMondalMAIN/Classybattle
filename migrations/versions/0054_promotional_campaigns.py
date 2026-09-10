"""promotional campaigns for automatic scheduled notifications

Revision ID: 0054_promotional_campaigns
Revises: 0053_min_lifetime_deposit_withdrawal
Create Date: 2026-09-10

Adds `promotional_campaigns`, the admin-defined schedule (once / daily /
every N hours) that `app.core.scheduler` reads to send push/email/in-app
promotional notifications automatically, without an admin having to
trigger each send manually.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0054_promotional_campaigns"
down_revision: Union[str, None] = "0053_min_lifetime_deposit_withdrawal"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # New NotificationEventType.PROMOTIONAL value for the notification_event_type
    # enum, used to tag notifications sent by promotional campaigns below.
    # ALTER TYPE ... ADD VALUE can't run inside the same transaction block
    # as other DDL on some PG versions, so it goes first and is committed
    # via autocommit before the rest of this migration proceeds.
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE notification_event_type ADD VALUE IF NOT EXISTS 'promotional'")

    schedule_type_enum = postgresql.ENUM(
        "once", "daily", "interval_hours", name="promotional_schedule_type"
    )
    schedule_type_enum.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "promotional_campaigns",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("body", sa.String(1000), nullable=False),
        sa.Column(
            "schedule_type",
            postgresql.ENUM(
                "once", "daily", "interval_hours",
                name="promotional_schedule_type",
                create_type=False,
            ),
            nullable=False,
        ),
        sa.Column("scheduled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("send_hour", sa.Integer(), nullable=True),
        sa.Column("send_minute", sa.Integer(), nullable=True),
        sa.Column("interval_hours", sa.Integer(), nullable=True),
        sa.Column("send_push", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("send_email", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("last_sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_recipient_count", sa.Integer(), nullable=True),
        sa.Column(
            "created_by_admin_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_promotional_campaigns_active_type",
        "promotional_campaigns",
        ["is_active", "schedule_type"],
    )


def downgrade() -> None:
    op.drop_index("ix_promotional_campaigns_active_type", table_name="promotional_campaigns")
    op.drop_table("promotional_campaigns")

    bind = op.get_bind()
    postgresql.ENUM(name="promotional_schedule_type").drop(bind, checkfirst=True)

    # Note: intentionally not removing 'promotional' from notification_event_type
    # -- Postgres has no ALTER TYPE ... DROP VALUE, and any existing
    # promotional notification rows would break if it were forcibly dropped.
