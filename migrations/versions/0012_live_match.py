"""live match & real-time tournament system - phase 12

Revision ID: 0012_live_match
Revises: 0011_match_results
Create Date: 2026-07-31

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0012_live_match"
down_revision: Union[str, None] = "0011_match_results"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _base_columns():
    return [
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False, unique=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    ]


def upgrade() -> None:
    live_match_status = postgresql.ENUM(
        "not_started", "live", "paused", "ended", "cancelled", name="live_match_status"
    )
    live_match_event_type = postgresql.ENUM(
        "match_started",
        "match_paused",
        "match_resumed",
        "match_ended",
        "match_cancelled",
        "round_started",
        "round_ended",
        "score_update",
        "kill",
        "elimination",
        "objective",
        "announcement",
        "other",
        name="live_match_event_type",
    )
    live_tournament_status = postgresql.ENUM(
        "not_started", "live", "completed", "cancelled", name="live_tournament_status"
    )

    bind = op.get_bind()
    live_match_status.create(bind, checkfirst=True)
    live_match_event_type.create(bind, checkfirst=True)
    live_tournament_status.create(bind, checkfirst=True)

    # ------------------------------------------------------------------
    # live_matches
    # ------------------------------------------------------------------
    op.create_table(
        "live_matches",
        *_base_columns(),
        sa.Column(
            "match_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("matches.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "tournament_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tournaments.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("status", live_match_status, nullable=False, server_default="not_started"),
        sa.Column("current_round", sa.Integer, nullable=False, server_default="1"),
        sa.Column("round_timer_seconds", sa.Integer, nullable=True),
        sa.Column("round_started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("paused_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("total_paused_seconds", sa.Integer, nullable=False, server_default="0"),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("auto_completion_processed", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("last_event_sequence", sa.Integer, nullable=False, server_default="0"),
        sa.UniqueConstraint("match_id", name="uq_live_matches_match_id"),
        sa.CheckConstraint(
            "total_paused_seconds >= 0", name="ck_live_matches_total_paused_non_negative"
        ),
        sa.CheckConstraint("current_round > 0", name="ck_live_matches_current_round_positive"),
    )
    op.create_index("ix_live_matches_match_id", "live_matches", ["match_id"])
    op.create_index("ix_live_matches_tournament_id", "live_matches", ["tournament_id"])
    op.create_index("ix_live_matches_status", "live_matches", ["status"])

    # ------------------------------------------------------------------
    # live_match_events
    # ------------------------------------------------------------------
    op.create_table(
        "live_match_events",
        *_base_columns(),
        sa.Column(
            "match_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("matches.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("sequence", sa.Integer, nullable=False),
        sa.Column("event_type", live_match_event_type, nullable=False),
        sa.Column("round_number", sa.Integer, nullable=True),
        sa.Column(
            "team_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("teams.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "participant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("participants.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("message", sa.String(500), nullable=True),
        sa.Column("event_metadata", postgresql.JSONB(), nullable=True),
        sa.Column("client_event_id", sa.String(100), nullable=True),
        sa.Column(
            "created_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.UniqueConstraint(
            "match_id", "client_event_id", name="uq_live_match_events_match_client_event"
        ),
    )
    op.create_index("ix_live_match_events_match_id", "live_match_events", ["match_id"])
    op.create_index("ix_live_match_events_event_type", "live_match_events", ["event_type"])
    op.create_index("ix_live_match_events_match_seq", "live_match_events", ["match_id", "sequence"])
    op.create_index(
        "ix_live_match_events_match_type", "live_match_events", ["match_id", "event_type"]
    )

    # ------------------------------------------------------------------
    # live_match_scores
    # ------------------------------------------------------------------
    op.create_table(
        "live_match_scores",
        *_base_columns(),
        sa.Column(
            "match_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("matches.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "team_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("teams.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column(
            "participant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("participants.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("kills", sa.Integer, nullable=False, server_default="0"),
        sa.Column("score", sa.Integer, nullable=False, server_default="0"),
        sa.Column("rank", sa.Integer, nullable=True),
        sa.Column("extra_stats", postgresql.JSONB(), nullable=True),
        sa.Column("last_updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("match_id", "team_id", name="uq_live_match_scores_match_team"),
        sa.UniqueConstraint(
            "match_id", "participant_id", name="uq_live_match_scores_match_participant"
        ),
        sa.CheckConstraint(
            "(team_id IS NOT NULL) OR (participant_id IS NOT NULL)",
            name="ck_live_match_scores_owner_present",
        ),
    )
    op.create_index("ix_live_match_scores_match_id", "live_match_scores", ["match_id"])
    op.create_index(
        "ix_live_match_scores_match_score", "live_match_scores", ["match_id", "score"]
    )

    # ------------------------------------------------------------------
    # live_tournament_states
    # ------------------------------------------------------------------
    op.create_table(
        "live_tournament_states",
        *_base_columns(),
        sa.Column(
            "tournament_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tournaments.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("status", live_tournament_status, nullable=False, server_default="not_started"),
        sa.Column("current_round", sa.Integer, nullable=False, server_default="1"),
        sa.Column("total_rounds", sa.Integer, nullable=True),
        sa.Column("total_matches", sa.Integer, nullable=False, server_default="0"),
        sa.Column("live_matches", sa.Integer, nullable=False, server_default="0"),
        sa.Column("completed_matches", sa.Integer, nullable=False, server_default="0"),
        sa.Column("last_progressed_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("tournament_id", name="uq_live_tournament_states_tournament_id"),
        sa.CheckConstraint("current_round > 0", name="ck_live_tournament_states_round_positive"),
    )
    op.create_index(
        "ix_live_tournament_states_tournament_id", "live_tournament_states", ["tournament_id"]
    )
    op.create_index("ix_live_tournament_states_status", "live_tournament_states", ["status"])


def downgrade() -> None:
    op.drop_index("ix_live_tournament_states_status", table_name="live_tournament_states")
    op.drop_index(
        "ix_live_tournament_states_tournament_id", table_name="live_tournament_states"
    )
    op.drop_table("live_tournament_states")

    op.drop_index("ix_live_match_scores_match_score", table_name="live_match_scores")
    op.drop_index("ix_live_match_scores_match_id", table_name="live_match_scores")
    op.drop_table("live_match_scores")

    op.drop_index("ix_live_match_events_match_type", table_name="live_match_events")
    op.drop_index("ix_live_match_events_match_seq", table_name="live_match_events")
    op.drop_index("ix_live_match_events_event_type", table_name="live_match_events")
    op.drop_index("ix_live_match_events_match_id", table_name="live_match_events")
    op.drop_table("live_match_events")

    op.drop_index("ix_live_matches_status", table_name="live_matches")
    op.drop_index("ix_live_matches_tournament_id", table_name="live_matches")
    op.drop_index("ix_live_matches_match_id", table_name="live_matches")
    op.drop_table("live_matches")

    bind = op.get_bind()
    postgresql.ENUM(name="live_tournament_status").drop(bind, checkfirst=True)
    postgresql.ENUM(name="live_match_event_type").drop(bind, checkfirst=True)
    postgresql.ENUM(name="live_match_status").drop(bind, checkfirst=True)
