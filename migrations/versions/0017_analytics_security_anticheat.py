"""analytics, admin dashboard, anti-cheat and security - phase 16

Revision ID: 0017_analytics_security_anticheat
Revises: 0016_achievements_moderation
Create Date: 2026-08-01

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0017_analytics_security_anticheat"
down_revision: Union[str, None] = "0016_achievements_moderation"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()

    security_event_type = postgresql.ENUM(
        "suspicious_login",
        "new_device_login",
        "multiple_failed_logins",
        "account_locked",
        "account_unlocked",
        "risk_score_updated",
        "duplicate_account",
        "duplicate_team",
        "multiple_registration",
        "match_abuse",
        "wallet_abuse",
        "other",
        name="security_event_type",
        create_type=False,
    )
    security_event_type.create(bind, checkfirst=True)

    security_event_severity = postgresql.ENUM(
        "low", "medium", "high", "critical", name="security_event_severity", create_type=False
    )
    security_event_severity.create(bind, checkfirst=True)

    fraud_flag_type = postgresql.ENUM(
        "duplicate_account",
        "multiple_registration",
        "duplicate_team",
        "match_abuse",
        "wallet_abuse",
        "suspicious_activity",
        name="fraud_flag_type",
        create_type=False,
    )
    fraud_flag_type.create(bind, checkfirst=True)

    fraud_flag_status = postgresql.ENUM(
        "open", "reviewing", "confirmed", "dismissed", name="fraud_flag_status", create_type=False
    )
    fraud_flag_status.create(bind, checkfirst=True)

    analytics_metric_type = postgresql.ENUM(
        "user", "tournament", "match", "wallet", "revenue", "prize", "registration", "dashboard",
        name="analytics_metric_type",
        create_type=False,
    )
    analytics_metric_type.create(bind, checkfirst=True)

    analytics_period_type = postgresql.ENUM(
        "daily", "weekly", "monthly", "custom", name="analytics_period_type", create_type=False
    )
    analytics_period_type.create(bind, checkfirst=True)

    # ------------------------------------------------------------------
    # login_history
    # ------------------------------------------------------------------
    op.create_table(
        "login_history",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("email_attempted", sa.String(255), nullable=True),
        sa.Column("success", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("failure_reason", sa.String(255), nullable=True),
        sa.Column("ip_address", sa.String(64), nullable=True),
        sa.Column("user_agent", sa.String(500), nullable=True),
        sa.Column("device_id", sa.String(255), nullable=True),
        sa.Column("platform", sa.String(50), nullable=True),
        sa.Column("is_new_device", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("is_new_ip", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("is_suspicious", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("risk_score", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_login_history_user_id", "login_history", ["user_id"])
    op.create_index("ix_login_history_user_created", "login_history", ["user_id", "created_at"])
    op.create_index("ix_login_history_ip", "login_history", ["ip_address"])

    # ------------------------------------------------------------------
    # security_events
    # ------------------------------------------------------------------
    op.create_table(
        "security_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("event_type", security_event_type, nullable=False),
        sa.Column("severity", security_event_severity, nullable=False, server_default="low"),
        sa.Column("description", sa.String(500), nullable=True),
        sa.Column("event_metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("ip_address", sa.String(64), nullable=True),
        sa.Column("resolved", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("resolved_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_security_events_user_id", "security_events", ["user_id"])
    op.create_index("ix_security_events_user_created", "security_events", ["user_id", "created_at"])
    op.create_index("ix_security_events_type", "security_events", ["event_type"])
    op.create_index("ix_security_events_resolved", "security_events", ["resolved"])

    # ------------------------------------------------------------------
    # account_locks
    # ------------------------------------------------------------------
    op.create_table(
        "account_locks",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("is_locked", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("reason", sa.String(500), nullable=True),
        sa.Column("risk_score", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("locked_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("locked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("unlocked_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("user_id", name="uq_account_locks_user_id"),
    )
    op.create_index("ix_account_locks_user_id", "account_locks", ["user_id"])

    # ------------------------------------------------------------------
    # fraud_flags
    # ------------------------------------------------------------------
    op.create_table(
        "fraud_flags",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("flag_type", fraud_flag_type, nullable=False),
        sa.Column("status", fraud_flag_status, nullable=False, server_default="open"),
        sa.Column("risk_score", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("related_entity_type", sa.String(50), nullable=False, server_default="none"),
        sa.Column("related_entity_id", sa.String(100), nullable=False, server_default=""),
        sa.Column("details", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("description", sa.String(500), nullable=True),
        sa.Column("reviewed_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("review_notes", sa.String(500), nullable=True),
        sa.UniqueConstraint(
            "user_id", "flag_type", "related_entity_type", "related_entity_id",
            name="uq_fraud_flags_user_type_entity",
        ),
    )
    op.create_index("ix_fraud_flags_user_id", "fraud_flags", ["user_id"])
    op.create_index("ix_fraud_flags_status", "fraud_flags", ["status"])
    op.create_index("ix_fraud_flags_type", "fraud_flags", ["flag_type"])

    # ------------------------------------------------------------------
    # analytics_snapshots
    # ------------------------------------------------------------------
    op.create_table(
        "analytics_snapshots",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("metric_type", analytics_metric_type, nullable=False),
        sa.Column("period_type", analytics_period_type, nullable=False),
        sa.Column("period_start", sa.Date(), nullable=False),
        sa.Column("period_end", sa.Date(), nullable=False),
        sa.Column("data", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.UniqueConstraint(
            "metric_type", "period_type", "period_start",
            name="uq_analytics_snapshots_metric_period",
        ),
    )
    op.create_index("ix_analytics_snapshots_period", "analytics_snapshots", ["period_type", "period_start"])


def downgrade() -> None:
    op.drop_table("analytics_snapshots")
    op.drop_table("fraud_flags")
    op.drop_table("account_locks")
    op.drop_table("security_events")
    op.drop_table("login_history")

    bind = op.get_bind()
    postgresql.ENUM(name="analytics_period_type").drop(bind, checkfirst=True)
    postgresql.ENUM(name="analytics_metric_type").drop(bind, checkfirst=True)
    postgresql.ENUM(name="fraud_flag_status").drop(bind, checkfirst=True)
    postgresql.ENUM(name="fraud_flag_type").drop(bind, checkfirst=True)
    postgresql.ENUM(name="security_event_severity").drop(bind, checkfirst=True)
    postgresql.ENUM(name="security_event_type").drop(bind, checkfirst=True)
