"""achievements and moderation system - phase 15c

Revision ID: 0016_achievements_moderation
Revises: 0015_team_community
Create Date: 2026-08-01

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0016_achievements_moderation"
down_revision: Union[str, None] = "0015_team_community"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    badge_tier = postgresql.ENUM("bronze", "silver", "gold", "platinum", name="badge_tier")
    badge_tier.create(op.get_bind(), checkfirst=True)

    achievement_trigger_type = postgresql.ENUM(
        "tournament_win",
        "tournament_participation",
        "match_win",
        "mvp",
        "ranking",
        "wallet_milestone",
        "prize_milestone",
        name="achievement_trigger_type",
    )
    achievement_trigger_type.create(op.get_bind(), checkfirst=True)

    achievement_comparison = postgresql.ENUM("gte", "lte", name="achievement_comparison")
    achievement_comparison.create(op.get_bind(), checkfirst=True)

    report_target_type = postgresql.ENUM("player", "team", "match", name="report_target_type")
    report_target_type.create(op.get_bind(), checkfirst=True)

    report_reason = postgresql.ENUM(
        "cheating",
        "harassment",
        "abusive_language",
        "no_show",
        "match_fixing",
        "impersonation",
        "spam",
        "other",
        name="report_reason",
    )
    report_reason.create(op.get_bind(), checkfirst=True)

    report_status = postgresql.ENUM(
        "pending", "under_review", "resolved", "dismissed", name="report_status"
    )
    report_status.create(op.get_bind(), checkfirst=True)

    moderation_action_type = postgresql.ENUM("warning", "suspension", "ban", name="moderation_action_type")
    moderation_action_type.create(op.get_bind(), checkfirst=True)

    moderation_action_status = postgresql.ENUM(
        "active", "expired", "revoked", name="moderation_action_status"
    )
    moderation_action_status.create(op.get_bind(), checkfirst=True)

    appeal_status = postgresql.ENUM("pending", "approved", "rejected", name="appeal_status")
    appeal_status.create(op.get_bind(), checkfirst=True)

    # ------------------------------------------------------------------
    # badges
    # ------------------------------------------------------------------
    op.create_table(
        "badges",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False, unique=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("name", sa.String(150), nullable=False),
        sa.Column("description", sa.String(500), nullable=True),
        sa.Column("icon_url", sa.String(1000), nullable=True),
        sa.Column("tier", badge_tier, nullable=False, server_default="bronze"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.UniqueConstraint("name", name="uq_badges_name"),
    )

    # ------------------------------------------------------------------
    # achievements
    # ------------------------------------------------------------------
    op.create_table(
        "achievements",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False, unique=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("code", sa.String(100), nullable=False),
        sa.Column("name", sa.String(150), nullable=False),
        sa.Column("description", sa.String(500), nullable=True),
        sa.Column("badge_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("badges.id", ondelete="CASCADE"), nullable=False),
        sa.Column("trigger_type", achievement_trigger_type, nullable=False),
        sa.Column("comparison", achievement_comparison, nullable=False, server_default="gte"),
        sa.Column("threshold", sa.Numeric(18, 2), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.UniqueConstraint("code", name="uq_achievements_code"),
    )
    op.create_index("ix_achievements_code", "achievements", ["code"])
    op.create_index("ix_achievements_badge_id", "achievements", ["badge_id"])
    op.create_index("ix_achievements_trigger_type", "achievements", ["trigger_type"])

    # ------------------------------------------------------------------
    # user_achievements
    # ------------------------------------------------------------------
    op.create_table(
        "user_achievements",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False, unique=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("achievement_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("achievements.id", ondelete="CASCADE"), nullable=False),
        sa.Column("unlocked_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("metric_value", sa.Numeric(18, 2), nullable=True),
        sa.Column("meta_data", postgresql.JSONB(), nullable=True),
        sa.UniqueConstraint("user_id", "achievement_id", name="uq_user_achievements_user_achievement"),
    )
    op.create_index("ix_user_achievements_user_id", "user_achievements", ["user_id"])
    op.create_index("ix_user_achievements_achievement_id", "user_achievements", ["achievement_id"])

    # ------------------------------------------------------------------
    # reports
    # ------------------------------------------------------------------
    op.create_table(
        "reports",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False, unique=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reporter_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("target_type", report_target_type, nullable=False),
        sa.Column("target_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("reason", report_reason, nullable=False),
        sa.Column("description", sa.String(2000), nullable=True),
        sa.Column("status", report_status, nullable=False, server_default="pending"),
        sa.Column("evidence_urls", postgresql.JSONB(), nullable=True),
        sa.Column("reviewed_by_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolution_notes", sa.String(2000), nullable=True),
    )
    op.create_index("ix_reports_reporter_id", "reports", ["reporter_id"])
    op.create_index("ix_reports_target_id", "reports", ["target_id"])
    op.create_index("ix_reports_status", "reports", ["status"])
    op.create_index("ix_reports_target", "reports", ["target_type", "target_id"])

    # ------------------------------------------------------------------
    # moderation_actions
    # ------------------------------------------------------------------
    op.create_table(
        "moderation_actions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False, unique=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("action_type", moderation_action_type, nullable=False),
        sa.Column("status", moderation_action_status, nullable=False, server_default="active"),
        sa.Column("reason", sa.String(1000), nullable=False),
        sa.Column("report_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("reports.id", ondelete="SET NULL"), nullable=True),
        sa.Column("issued_by_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_reason", sa.String(1000), nullable=True),
    )
    op.create_index("ix_moderation_actions_user_id", "moderation_actions", ["user_id"])
    op.create_index("ix_moderation_actions_action_type", "moderation_actions", ["action_type"])
    op.create_index("ix_moderation_actions_status", "moderation_actions", ["status"])

    # ------------------------------------------------------------------
    # appeals
    # ------------------------------------------------------------------
    op.create_table(
        "appeals",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False, unique=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("moderation_action_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("moderation_actions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("message", sa.String(2000), nullable=False),
        sa.Column("status", appeal_status, nullable=False, server_default="pending"),
        sa.Column("reviewed_by_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("review_notes", sa.String(2000), nullable=True),
    )
    op.create_index("ix_appeals_moderation_action_id", "appeals", ["moderation_action_id"])
    op.create_index("ix_appeals_user_id", "appeals", ["user_id"])
    op.create_index("ix_appeals_status", "appeals", ["status"])


def downgrade() -> None:
    op.drop_table("appeals")
    op.drop_table("moderation_actions")
    op.drop_table("reports")
    op.drop_table("user_achievements")
    op.drop_table("achievements")
    op.drop_table("badges")

    bind = op.get_bind()
    postgresql.ENUM(name="appeal_status").drop(bind, checkfirst=True)
    postgresql.ENUM(name="moderation_action_status").drop(bind, checkfirst=True)
    postgresql.ENUM(name="moderation_action_type").drop(bind, checkfirst=True)
    postgresql.ENUM(name="report_status").drop(bind, checkfirst=True)
    postgresql.ENUM(name="report_reason").drop(bind, checkfirst=True)
    postgresql.ENUM(name="report_target_type").drop(bind, checkfirst=True)
    postgresql.ENUM(name="achievement_comparison").drop(bind, checkfirst=True)
    postgresql.ENUM(name="achievement_trigger_type").drop(bind, checkfirst=True)
    postgresql.ENUM(name="badge_tier").drop(bind, checkfirst=True)
