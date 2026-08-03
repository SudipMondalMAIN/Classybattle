"""admin match-details: kills, winner, payout

Revision ID: 0027_match_admin_results
Revises: 0026_simplified_match_schedule
Create Date: 2026-08-03

Admin match-details page (Raj's flow): per-player kills, winner flag,
and winning amount payout, tracked directly on the slot a player
occupies — MatchParticipant for solo joins, MatchTeamMember for squad
joins (one row per teammate).
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "0027_match_admin_results"
down_revision = "0026_simplified_match_schedule"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "match_participants",
        sa.Column("kills", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "match_participants",
        sa.Column("is_winner", sa.Boolean(), nullable=False, server_default="false"),
    )
    op.create_index(
        "ix_match_participants_is_winner", "match_participants", ["is_winner"]
    )
    op.add_column(
        "match_participants",
        sa.Column("winning_amount", sa.Numeric(12, 2), nullable=True),
    )
    op.add_column(
        "match_participants",
        sa.Column("winning_paid_at", sa.DateTime(timezone=True), nullable=True),
    )

    op.add_column(
        "match_team_members",
        sa.Column("kills", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "match_team_members",
        sa.Column("is_winner", sa.Boolean(), nullable=False, server_default="false"),
    )
    op.create_index(
        "ix_match_team_members_is_winner", "match_team_members", ["is_winner"]
    )
    op.add_column(
        "match_team_members",
        sa.Column("winning_amount", sa.Numeric(12, 2), nullable=True),
    )
    op.add_column(
        "match_team_members",
        sa.Column("winning_paid_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("match_team_members", "winning_paid_at")
    op.drop_column("match_team_members", "winning_amount")
    op.drop_index("ix_match_team_members_is_winner", table_name="match_team_members")
    op.drop_column("match_team_members", "is_winner")
    op.drop_column("match_team_members", "kills")

    op.drop_column("match_participants", "winning_paid_at")
    op.drop_column("match_participants", "winning_amount")
    op.drop_index("ix_match_participants_is_winner", table_name="match_participants")
    op.drop_column("match_participants", "is_winner")
    op.drop_column("match_participants", "kills")
