"""add rank column for multi-winner (1st/2nd/3rd) support

Revision ID: 0032_winner_rank
Revises: 0031_app_versions
Create Date: 2026-08-09

Adds a nullable `rank` (1, 2, 3, ...) column next to the existing
`is_winner` boolean on both TournamentParticipant (solo) and
TournamentTeamMember (squad) rows, so Raj's admin "tournament details"
result-entry flow can declare several ranked winners per tournament,
not just a single is_winner=true player.
"""
import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "0032_winner_rank"
down_revision = "0031_app_versions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "tournament_participants", sa.Column("rank", sa.Integer(), nullable=True)
    )
    op.create_index(
        "ix_tournament_participants_rank", "tournament_participants", ["rank"]
    )

    op.add_column(
        "tournament_team_members", sa.Column("rank", sa.Integer(), nullable=True)
    )
    op.create_index(
        "ix_tournament_team_members_rank", "tournament_team_members", ["rank"]
    )


def downgrade() -> None:
    op.drop_index("ix_tournament_team_members_rank", table_name="tournament_team_members")
    op.drop_column("tournament_team_members", "rank")

    op.drop_index("ix_tournament_participants_rank", table_name="tournament_participants")
    op.drop_column("tournament_participants", "rank")
