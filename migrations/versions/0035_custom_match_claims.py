"""add custom_match_claims table for 1v1 custom-tournament self-declared results

Revision ID: 0035_custom_match_claims
Revises: 0034_home_category_boxes
Create Date: 2026-08-14

Custom (user-hosted) 1v1 tournaments have no admin refereeing the match,
so each player self-reports win/loss instead. LOSS needs no proof and
instantly pays out the other player; WIN requires a proof screenshot and
waits for the opponent's confirming claim or an admin review. See
app/models/custom_match_claim.py for the full rules.
"""
import uuid

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "0035_custom_match_claims"
down_revision = "0034_home_category_boxes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()

    outcome_enum = postgresql.ENUM(
        "win", "loss", name="custom_match_claim_outcome", create_type=False
    )
    outcome_enum.create(bind, checkfirst=True)

    status_enum = postgresql.ENUM(
        "pending_review", "auto_resolved", "admin_approved", "rejected",
        name="custom_match_claim_status", create_type=False,
    )
    status_enum.create(bind, checkfirst=True)

    op.create_table(
        "custom_match_claims",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            default=uuid.uuid4,
            nullable=False,
        ),
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
            "tournament_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tournaments.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("outcome", outcome_enum, nullable=False),
        sa.Column("proof_url", sa.String(length=500), nullable=True),
        sa.Column("status", status_enum, nullable=False, server_default="pending_review"),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "resolved_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("rejection_reason", sa.Text(), nullable=True),
        sa.UniqueConstraint(
            "tournament_id", "user_id", name="uq_custom_match_claims_tournament_user"
        ),
    )
    op.create_index(
        "ix_custom_match_claims_tournament_id", "custom_match_claims", ["tournament_id"]
    )
    op.create_index("ix_custom_match_claims_user_id", "custom_match_claims", ["user_id"])
    op.create_index("ix_custom_match_claims_status", "custom_match_claims", ["status"])
    op.create_index(
        "ix_custom_match_claims_tournament_status",
        "custom_match_claims",
        ["tournament_id", "status"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_custom_match_claims_tournament_status", table_name="custom_match_claims"
    )
    op.drop_index("ix_custom_match_claims_status", table_name="custom_match_claims")
    op.drop_index("ix_custom_match_claims_user_id", table_name="custom_match_claims")
    op.drop_index("ix_custom_match_claims_tournament_id", table_name="custom_match_claims")
    op.drop_table("custom_match_claims")

    bind = op.get_bind()
    postgresql.ENUM(name="custom_match_claim_status").drop(bind, checkfirst=True)
    postgresql.ENUM(name="custom_match_claim_outcome").drop(bind, checkfirst=True)
