"""leaderboard, ranking & player/team statistics - phase 14

Revision ID: 0024_leaderboard
Revises: 0023_short_ids
Create Date: 2026-08-03

Adds the tables backing app/models/leaderboard.py, which existed in the
ORM but had no corresponding migration yet (causing
`relation "player_statistics" does not exist` at query time):

- player_statistics / team_statistics: single mutable all-time
  aggregate + current rank row per user / team.
- player_period_stats / team_period_stats: rolling-period (daily/
  weekly/monthly/seasonal) counters keyed by (entity, period_type,
  period_key).
- rank_history: immutable append-only ledger of rank changes.
- leaderboard_update_log: idempotency guard so a retried trigger can
  never double-count a source event.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0024_leaderboard"
down_revision: Union[str, None] = "0023_short_ids"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ------------------------------------------------------------------
    # player_statistics
    # ------------------------------------------------------------------
    op.create_table(
        "player_statistics",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("matches_played", sa.Integer(), server_default="0", nullable=False),
        sa.Column("matches_won", sa.Integer(), server_default="0", nullable=False),
        sa.Column("matches_lost", sa.Integer(), server_default="0", nullable=False),
        sa.Column("kills", sa.Integer(), server_default="0", nullable=False),
        sa.Column("deaths", sa.Integer(), server_default="0", nullable=False),
        sa.Column("assists", sa.Integer(), server_default="0", nullable=False),
        sa.Column("mvp_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("tournaments_played", sa.Integer(), server_default="0", nullable=False),
        sa.Column("tournaments_won", sa.Integer(), server_default="0", nullable=False),
        sa.Column("prize_money_earned", sa.Numeric(14, 2), server_default="0", nullable=False),
        sa.Column("wallet_earnings", sa.Numeric(14, 2), server_default="0", nullable=False),
        sa.Column("ranking_score", sa.Numeric(14, 4), server_default="0", nullable=False),
        sa.Column("current_rank", sa.Integer(), nullable=True),
        sa.Column("previous_rank", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("user_id", name="uq_player_statistics_user_id"),
    )
    op.create_index("ix_player_statistics_user_id", "player_statistics", ["user_id"])
    op.create_index("ix_player_statistics_rank", "player_statistics", ["current_rank"])
    op.create_index("ix_player_statistics_score", "player_statistics", ["ranking_score"])

    # ------------------------------------------------------------------
    # team_statistics
    # ------------------------------------------------------------------
    op.create_table(
        "team_statistics",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("team_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("matches_played", sa.Integer(), server_default="0", nullable=False),
        sa.Column("matches_won", sa.Integer(), server_default="0", nullable=False),
        sa.Column("matches_lost", sa.Integer(), server_default="0", nullable=False),
        sa.Column("tournaments_played", sa.Integer(), server_default="0", nullable=False),
        sa.Column("tournaments_won", sa.Integer(), server_default="0", nullable=False),
        sa.Column("prize_money_earned", sa.Numeric(14, 2), server_default="0", nullable=False),
        sa.Column("placement_total", sa.Integer(), server_default="0", nullable=False),
        sa.Column("ranking_score", sa.Numeric(14, 4), server_default="0", nullable=False),
        sa.Column("current_rank", sa.Integer(), nullable=True),
        sa.Column("previous_rank", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(["team_id"], ["teams.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("team_id", name="uq_team_statistics_team_id"),
    )
    op.create_index("ix_team_statistics_team_id", "team_statistics", ["team_id"])
    op.create_index("ix_team_statistics_rank", "team_statistics", ["current_rank"])
    op.create_index("ix_team_statistics_score", "team_statistics", ["ranking_score"])

    # ------------------------------------------------------------------
    # player_period_stats
    # ------------------------------------------------------------------
    op.create_table(
        "player_period_stats",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("period_type", sa.String(20), nullable=False),
        sa.Column("period_key", sa.String(20), nullable=False),
        sa.Column("matches_played", sa.Integer(), server_default="0", nullable=False),
        sa.Column("matches_won", sa.Integer(), server_default="0", nullable=False),
        sa.Column("kills", sa.Integer(), server_default="0", nullable=False),
        sa.Column("deaths", sa.Integer(), server_default="0", nullable=False),
        sa.Column("assists", sa.Integer(), server_default="0", nullable=False),
        sa.Column("mvp_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("prize_money_earned", sa.Numeric(14, 2), server_default="0", nullable=False),
        sa.Column("ranking_score", sa.Numeric(14, 4), server_default="0", nullable=False),
        sa.Column("current_rank", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.UniqueConstraint(
            "user_id", "period_type", "period_key", name="uq_player_period_stats_user_period"
        ),
    )
    op.create_index("ix_player_period_stats_user_id", "player_period_stats", ["user_id"])
    op.create_index("ix_player_period_stats_period_type", "player_period_stats", ["period_type"])
    op.create_index("ix_player_period_stats_period_key", "player_period_stats", ["period_key"])
    op.create_index(
        "ix_player_period_stats_lookup",
        "player_period_stats",
        ["period_type", "period_key", "ranking_score"],
    )

    # ------------------------------------------------------------------
    # team_period_stats
    # ------------------------------------------------------------------
    op.create_table(
        "team_period_stats",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("team_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("period_type", sa.String(20), nullable=False),
        sa.Column("period_key", sa.String(20), nullable=False),
        sa.Column("matches_played", sa.Integer(), server_default="0", nullable=False),
        sa.Column("matches_won", sa.Integer(), server_default="0", nullable=False),
        sa.Column("prize_money_earned", sa.Numeric(14, 2), server_default="0", nullable=False),
        sa.Column("ranking_score", sa.Numeric(14, 4), server_default="0", nullable=False),
        sa.Column("current_rank", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(["team_id"], ["teams.id"], ondelete="CASCADE"),
        sa.UniqueConstraint(
            "team_id", "period_type", "period_key", name="uq_team_period_stats_team_period"
        ),
    )
    op.create_index("ix_team_period_stats_team_id", "team_period_stats", ["team_id"])
    op.create_index("ix_team_period_stats_period_type", "team_period_stats", ["period_type"])
    op.create_index("ix_team_period_stats_period_key", "team_period_stats", ["period_key"])
    op.create_index(
        "ix_team_period_stats_lookup",
        "team_period_stats",
        ["period_type", "period_key", "ranking_score"],
    )

    # ------------------------------------------------------------------
    # rank_history
    # ------------------------------------------------------------------
    op.create_table(
        "rank_history",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("scope", sa.String(30), nullable=False),
        sa.Column("entity_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("team_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("tournament_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("old_rank", sa.Integer(), nullable=True),
        sa.Column("new_rank", sa.Integer(), nullable=True),
        sa.Column("ranking_score", sa.Numeric(14, 4), server_default="0", nullable=False),
        sa.Column("source_event", sa.String(30), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["team_id"], ["teams.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tournament_id"], ["tournaments.id"], ondelete="CASCADE"),
        sa.CheckConstraint(
            "(user_id IS NOT NULL) OR (team_id IS NOT NULL)",
            name="ck_rank_history_user_or_team",
        ),
    )
    op.create_index("ix_rank_history_scope", "rank_history", ["scope"])
    op.create_index("ix_rank_history_entity_id", "rank_history", ["entity_id"])
    op.create_index("ix_rank_history_user_id", "rank_history", ["user_id"])
    op.create_index("ix_rank_history_team_id", "rank_history", ["team_id"])
    op.create_index("ix_rank_history_tournament_id", "rank_history", ["tournament_id"])
    op.create_index(
        "ix_rank_history_entity", "rank_history", ["scope", "entity_id", "created_at"]
    )

    # ------------------------------------------------------------------
    # leaderboard_update_log
    # ------------------------------------------------------------------
    op.create_table(
        "leaderboard_update_log",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("source_event", sa.String(30), nullable=False),
        sa.Column("source_id", sa.String(100), nullable=False),
        sa.Column("detail", sa.String(500), nullable=True),
        sa.UniqueConstraint(
            "source_event", "source_id", name="uq_leaderboard_update_log_source"
        ),
    )


def downgrade() -> None:
    op.drop_table("leaderboard_update_log")

    op.drop_index("ix_rank_history_entity", table_name="rank_history")
    op.drop_index("ix_rank_history_tournament_id", table_name="rank_history")
    op.drop_index("ix_rank_history_team_id", table_name="rank_history")
    op.drop_index("ix_rank_history_user_id", table_name="rank_history")
    op.drop_index("ix_rank_history_entity_id", table_name="rank_history")
    op.drop_index("ix_rank_history_scope", table_name="rank_history")
    op.drop_table("rank_history")

    op.drop_index("ix_team_period_stats_lookup", table_name="team_period_stats")
    op.drop_index("ix_team_period_stats_period_key", table_name="team_period_stats")
    op.drop_index("ix_team_period_stats_period_type", table_name="team_period_stats")
    op.drop_index("ix_team_period_stats_team_id", table_name="team_period_stats")
    op.drop_table("team_period_stats")

    op.drop_index("ix_player_period_stats_lookup", table_name="player_period_stats")
    op.drop_index("ix_player_period_stats_period_key", table_name="player_period_stats")
    op.drop_index("ix_player_period_stats_period_type", table_name="player_period_stats")
    op.drop_index("ix_player_period_stats_user_id", table_name="player_period_stats")
    op.drop_table("player_period_stats")

    op.drop_index("ix_team_statistics_score", table_name="team_statistics")
    op.drop_index("ix_team_statistics_rank", table_name="team_statistics")
    op.drop_index("ix_team_statistics_team_id", table_name="team_statistics")
    op.drop_table("team_statistics")

    op.drop_index("ix_player_statistics_score", table_name="player_statistics")
    op.drop_index("ix_player_statistics_rank", table_name="player_statistics")
    op.drop_index("ix_player_statistics_user_id", table_name="player_statistics")
    op.drop_table("player_statistics")
