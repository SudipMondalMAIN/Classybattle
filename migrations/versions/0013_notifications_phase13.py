"""enterprise notification & communication system - phase 13

Revision ID: 0013_notifications
Revises: 0012_live_match
Create Date: 2026-08-01

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0013_notifications"
down_revision: Union[str, None] = "0012_live_match"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    notification_event_type = postgresql.ENUM(
        "general",
        "user_registration",
        "tournament_created",
        "tournament_updated",
        "tournament_cancelled",
        "registration_successful",
        "registration_cancelled",
        "match_created",
        "match_started",
        "match_completed",
        "live_match_started",
        "match_result_approved",
        "winner_declared",
        "prize_distributed",
        "wallet_credited",
        "wallet_debited",
        "refund_completed",
        "admin_broadcast",
        "system_announcement",
        name="notification_event_type",
    )
    notification_event_type.create(op.get_bind(), checkfirst=True)

    op.add_column(
        "notifications",
        sa.Column(
            "event_type",
            notification_event_type,
            nullable=False,
            server_default="general",
        ),
    )
    op.add_column(
        "notifications",
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "notifications",
        sa.Column("event_key", sa.String(length=255), nullable=True),
    )
    op.create_index("ix_notifications_event_type", "notifications", ["event_type"])
    op.create_index("ix_notifications_event_key", "notifications", ["event_key"])
    op.create_unique_constraint("uq_notifications_event_key", "notifications", ["event_key"])

    op.create_table(
        "notification_preferences",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False, unique=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("in_app_enabled", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("push_enabled", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("email_enabled", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.UniqueConstraint("user_id", name="uq_notification_preferences_user_id"),
    )
    op.create_index(
        "ix_notification_preferences_user_id", "notification_preferences", ["user_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_notification_preferences_user_id", table_name="notification_preferences")
    op.drop_table("notification_preferences")

    op.drop_constraint("uq_notifications_event_key", "notifications", type_="unique")
    op.drop_index("ix_notifications_event_key", table_name="notifications")
    op.drop_index("ix_notifications_event_type", table_name="notifications")
    op.drop_column("notifications", "event_key")
    op.drop_column("notifications", "read_at")
    op.drop_column("notifications", "event_type")

    bind = op.get_bind()
    postgresql.ENUM(name="notification_event_type").drop(bind, checkfirst=True)
