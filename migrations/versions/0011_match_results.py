"""match result & winner management system - phase 11

Revision ID: 0011_match_results
Revises: 0010_prize_distribution
Create Date: 2026-07-31

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0011_match_results"
down_revision: Union[str, None] = "0010_prize_distribution"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    match_result_status = postgresql.ENUM(
        "submitted", "verified", "approved", "rejected", name="match_result_status", create_type=False
    )
    winner_assignment_source = postgresql.ENUM(
        "automatic", "manual", name="winner_assignment_source", create_type=False
    )
    bind = op.get_bind()
    match_result_status.create(bind, checkfirst=True)
    winner_assignment_source.create(bind, checkfirst=True)

    # ------------------------------------------------------------------
    # match_results
    # ------------------------------------------------------------------
    op.create_table(
        "match_results",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("match_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tournament_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("result_data", postgresql.JSONB(), nullable=False),
        sa.Column("is_tie", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("status", match_result_status, server_default="submitted", nullable=False),
        sa.Column("submitted_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("verified_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("approved_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("rejected_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("rejected_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("rejection_reason", sa.String(500), nullable=True),
        sa.Column(
            "prize_distribution_triggered", sa.Boolean(), server_default=sa.text("false"), nullable=False
        ),
        sa.Column("prize_distribution_triggered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["match_id"], ["matches.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tournament_id"], ["tournaments.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["submitted_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["verified_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["approved_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["rejected_by"], ["users.id"], ondelete="SET NULL"),
        sa.UniqueConstraint("match_id", name="uq_match_results_match_id"),
    )
    op.create_index("ix_match_results_match_id", "match_results", ["match_id"])
    op.create_index("ix_match_results_tournament_id", "match_results", ["tournament_id"])
    op.create_index("ix_match_results_status", "match_results", ["status"])
    op.create_index(
        "ix_match_results_tournament_status", "match_results", ["tournament_id", "status"]
    )

    # ------------------------------------------------------------------
    # match_winners
    # ------------------------------------------------------------------
    op.create_table(
        "match_winners",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("match_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("match_result_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tournament_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("team_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("participant_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("rank", sa.Integer(), nullable=False),
        sa.Column("is_tie", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column(
            "assignment_source", winner_assignment_source, server_default="automatic", nullable=False
        ),
        sa.Column("is_manual_override", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("declared_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("declared_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["match_id"], ["matches.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["match_result_id"], ["match_results.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tournament_id"], ["tournaments.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["team_id"], ["teams.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["participant_id"], ["participants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["declared_by"], ["users.id"], ondelete="SET NULL"),
        sa.UniqueConstraint("match_id", "rank", "team_id", name="uq_match_winners_match_rank_team"),
        sa.UniqueConstraint(
            "match_id", "rank", "participant_id", name="uq_match_winners_match_rank_participant"
        ),
        sa.UniqueConstraint("match_id", "team_id", name="uq_match_winners_match_team"),
        sa.UniqueConstraint("match_id", "participant_id", name="uq_match_winners_match_participant"),
        sa.CheckConstraint("rank > 0", name="ck_match_winners_rank_positive"),
        sa.CheckConstraint(
            "(team_id IS NOT NULL) OR (participant_id IS NOT NULL)",
            name="ck_match_winners_team_or_participant",
        ),
    )
    op.create_index("ix_match_winners_match_id", "match_winners", ["match_id"])
    op.create_index("ix_match_winners_match_result_id", "match_winners", ["match_result_id"])
    op.create_index("ix_match_winners_tournament_id", "match_winners", ["tournament_id"])
    op.create_index("ix_match_winners_team_id", "match_winners", ["team_id"])
    op.create_index("ix_match_winners_participant_id", "match_winners", ["participant_id"])
    op.create_index("ix_match_winners_match_rank", "match_winners", ["match_id", "rank"])


def downgrade() -> None:
    op.drop_table("match_winners")
    op.drop_table("match_results")

    bind = op.get_bind()
    postgresql.ENUM(name="winner_assignment_source").drop(bind, checkfirst=True)
    postgresql.ENUM(name="match_result_status").drop(bind, checkfirst=True)
