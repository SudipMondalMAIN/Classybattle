"""referral system v2 -- config, referrals, milestone claims

Revision ID: 0048_referral_system
Revises: 0047_maintenance_config
Create Date: 2026-08-28

Adds:
- users.referral_code (unique, nullable -- backfilled lazily by
  ReferralService for pre-existing users on their first referral
  interaction; new signups get one immediately).
- referral_config: single global row, fully admin-tunable.
- referrals: one row per referee (uq on referee_id).
- referral_milestone_claims: one row per (referrer, threshold) already paid.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0048_referral_system"
down_revision: Union[str, None] = "0047_maintenance_config"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    referral_status = postgresql.ENUM(
        "pending", "on_hold", "completed", "rejected", name="referral_status", create_type=False
    )
    bind = op.get_bind()
    referral_status.create(bind, checkfirst=True)

    # ------------------------------------------------------------------
    # users.referral_code
    # ------------------------------------------------------------------
    op.add_column("users", sa.Column("referral_code", sa.String(length=16), nullable=True))
    op.create_index("ix_users_referral_code", "users", ["referral_code"], unique=True)

    # ------------------------------------------------------------------
    # referral_config
    # ------------------------------------------------------------------
    op.create_table(
        "referral_config",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reward_amount", sa.Numeric(14, 2), server_default="10", nullable=False),
        sa.Column("min_deposit_amount", sa.Numeric(14, 2), server_default="20", nullable=False),
        sa.Column("require_deposit_step", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("require_paid_tournament_step", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("apply_window_days", sa.Integer(), server_default="30", nullable=False),
        sa.Column("fraud_check_enabled", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("max_accounts_per_ip", sa.Integer(), server_default="5", nullable=False),
        sa.Column("milestone_rules", postgresql.JSONB(), server_default="[]", nullable=False),
    )

    # Seed the single default row (default milestone ladder baked in here
    # so a fresh DB has sane config before any admin touches it).
    op.execute(
        """
        INSERT INTO referral_config (id, milestone_rules)
        VALUES (
            gen_random_uuid(),
            '[{"threshold": 10, "bonus": "10"}, {"threshold": 20, "bonus": "10"},
              {"threshold": 30, "bonus": "10"}, {"threshold": 40, "bonus": "10"},
              {"threshold": 50, "bonus": "30"}, {"threshold": 100, "bonus": "50"}]'::jsonb
        )
        """
    )

    # ------------------------------------------------------------------
    # referrals
    # ------------------------------------------------------------------
    op.create_table(
        "referrals",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("referrer_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("referee_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("code_used", sa.String(length=16), nullable=False),
        sa.Column("status", referral_status, server_default="pending", nullable=False),
        sa.Column("deposit_met", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("deposit_met_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("tournament_met", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("tournament_met_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ip_address", sa.String(length=64), nullable=True),
        sa.Column("device_id", sa.String(length=255), nullable=True),
        sa.Column("risk_flagged", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("risk_reason", sa.Text(), nullable=True),
        sa.Column("reward_amount", sa.Numeric(14, 2), nullable=True),
        sa.Column("reward_credited", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("credited_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("wallet_transaction_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("reviewed_by_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("admin_note", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["referrer_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["referee_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["wallet_transaction_id"], ["wallet_transactions.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["reviewed_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.UniqueConstraint("referee_id", name="uq_referrals_referee_id"),
    )
    op.create_index("ix_referrals_referrer_id", "referrals", ["referrer_id"])
    op.create_index("ix_referrals_status", "referrals", ["status"])
    op.create_index("ix_referrals_referrer_status", "referrals", ["referrer_id", "status"])
    op.create_index("ix_referrals_ip", "referrals", ["ip_address"])
    op.create_index("ix_referrals_device", "referrals", ["device_id"])

    # ------------------------------------------------------------------
    # referral_milestone_claims
    # ------------------------------------------------------------------
    op.create_table(
        "referral_milestone_claims",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("referrer_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("threshold", sa.Integer(), nullable=False),
        sa.Column("bonus_amount", sa.Numeric(14, 2), nullable=False),
        sa.Column("wallet_transaction_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.ForeignKeyConstraint(["referrer_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["wallet_transaction_id"], ["wallet_transactions.id"], ondelete="SET NULL"),
        sa.UniqueConstraint("referrer_id", "threshold", name="uq_referral_milestone_referrer_threshold"),
    )
    op.create_index("ix_referral_milestone_claims_referrer_id", "referral_milestone_claims", ["referrer_id"])


def downgrade() -> None:
    op.drop_table("referral_milestone_claims")
    op.drop_index("ix_referrals_device", table_name="referrals")
    op.drop_index("ix_referrals_ip", table_name="referrals")
    op.drop_index("ix_referrals_referrer_status", table_name="referrals")
    op.drop_index("ix_referrals_status", table_name="referrals")
    op.drop_index("ix_referrals_referrer_id", table_name="referrals")
    op.drop_table("referrals")
    op.drop_table("referral_config")
    op.drop_index("ix_users_referral_code", table_name="users")
    op.drop_column("users", "referral_code")
    referral_status = postgresql.ENUM(name="referral_status")
    referral_status.drop(op.get_bind(), checkfirst=True)
