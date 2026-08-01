"""room management & match lifecycle - phase 7

Revision ID: 0007_matches
Revises: 0006_teams
Create Date: 2026-07-30

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0007_matches"
down_revision: Union[str, None] = "0006_teams"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _base_columns():
    return [
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False, unique=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    ]


def upgrade() -> None:
    bind = op.get_bind()

    # ------------------------------------------------------------------
    # matches
    # ------------------------------------------------------------------
    match_room_status = postgresql.ENUM(
        "not_created", "hidden", "published", "edited", "closed",
        name="match_room_status",
        create_type=False,
    )
    match_room_status.create(bind, checkfirst=True)

    match_status = postgresql.ENUM(
        "draft", "scheduled", "room_published", "check_in_open", "ready",
        "live", "completed", "cancelled",
        name="match_status",
        create_type=False,
    )
    match_status.create(bind, checkfirst=True)

    op.create_table(
        "matches",
        *_base_columns(),
        sa.Column("match_uid", sa.String(20), nullable=False),
        sa.Column(
            "tournament_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tournaments.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("round_number", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("match_number", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("room_name", sa.String(150), nullable=True),
        sa.Column("room_id", sa.String(100), nullable=True),
        sa.Column("room_password", sa.String(100), nullable=True),
        sa.Column("room_status", match_room_status, nullable=False, server_default="not_created"),
        sa.Column("room_published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("match_status", match_status, nullable=False, server_default="draft"),
        sa.Column("scheduled_start", sa.DateTime(timezone=True), nullable=True),
        sa.Column("scheduled_end", sa.DateTime(timezone=True), nullable=True),
        sa.Column("actual_start", sa.DateTime(timezone=True), nullable=True),
        sa.Column("actual_end", sa.DateTime(timezone=True), nullable=True),
        sa.Column("check_in_opens_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("check_in_deadline", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "auto_disqualify_on_no_show", sa.Boolean(), nullable=False, server_default=sa.true()
        ),
        sa.Column(
            "winner_team_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("teams.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column(
            "created_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.UniqueConstraint("match_uid", name="uq_matches_match_uid"),
        sa.UniqueConstraint(
            "tournament_id", "round_number", "match_number",
            name="uq_matches_tournament_round_match_number",
        ),
        sa.CheckConstraint("round_number > 0", name="ck_matches_round_number_positive"),
        sa.CheckConstraint("match_number > 0", name="ck_matches_match_number_positive"),
        sa.CheckConstraint(
            "scheduled_end IS NULL OR scheduled_start IS NULL OR scheduled_end > scheduled_start",
            name="ck_matches_scheduled_window_valid",
        ),
        sa.CheckConstraint(
            "actual_end IS NULL OR actual_start IS NULL OR actual_end >= actual_start",
            name="ck_matches_actual_window_valid",
        ),
    )

    op.create_index("ix_matches_match_uid", "matches", ["match_uid"])
    op.create_index("ix_matches_tournament_id", "matches", ["tournament_id"])
    op.create_index("ix_matches_room_status", "matches", ["room_status"])
    op.create_index("ix_matches_match_status", "matches", ["match_status"])
    op.create_index("ix_matches_winner_team_id", "matches", ["winner_team_id"])
    op.create_index("ix_matches_created_by", "matches", ["created_by"])
    op.create_index("ix_matches_tournament_status", "matches", ["tournament_id", "match_status"])
    op.create_index("ix_matches_tournament_round", "matches", ["tournament_id", "round_number"])

    # ------------------------------------------------------------------
    # match_participants
    # ------------------------------------------------------------------
    match_assignment_type = postgresql.ENUM(
        "registered", "random", "manual", "auto", name="match_assignment_type", create_type=False
    )
    match_assignment_type.create(bind, checkfirst=True)

    match_check_in_status = postgresql.ENUM(
        "not_open", "pending", "checked_in", "late_checked_in", "no_show",
        name="match_check_in_status",
        create_type=False,
    )
    match_check_in_status.create(bind, checkfirst=True)

    op.create_table(
        "match_participants",
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
        sa.Column("slot_number", sa.Integer(), nullable=False),
        sa.Column(
            "assignment_type", match_assignment_type, nullable=False, server_default="registered"
        ),
        sa.Column(
            "assigned_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "check_in_status", match_check_in_status, nullable=False, server_default="not_open"
        ),
        sa.Column("checked_in_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "checked_in_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "is_organizer_override", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
        sa.Column("is_disqualified", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("disqualified_reason", sa.String(255), nullable=True),
        sa.Column("replaced_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint(
            "match_id", "slot_number", name="uq_match_participants_match_slot"
        ),
        sa.UniqueConstraint("match_id", "team_id", name="uq_match_participants_match_team"),
        sa.UniqueConstraint(
            "match_id", "participant_id", name="uq_match_participants_match_participant"
        ),
        sa.CheckConstraint("slot_number > 0", name="ck_match_participants_slot_positive"),
        sa.CheckConstraint(
            "(team_id IS NOT NULL) OR (participant_id IS NOT NULL)",
            name="ck_match_participants_team_or_participant",
        ),
    )

    op.create_index("ix_match_participants_match_id", "match_participants", ["match_id"])
    op.create_index("ix_match_participants_team_id", "match_participants", ["team_id"])
    op.create_index(
        "ix_match_participants_participant_id", "match_participants", ["participant_id"]
    )
    op.create_index(
        "ix_match_participants_check_in_status", "match_participants", ["check_in_status"]
    )
    op.create_index(
        "ix_match_participants_match_checkin",
        "match_participants",
        ["match_id", "check_in_status"],
    )


def downgrade() -> None:
    op.drop_index("ix_match_participants_match_checkin", table_name="match_participants")
    op.drop_index("ix_match_participants_check_in_status", table_name="match_participants")
    op.drop_index("ix_match_participants_participant_id", table_name="match_participants")
    op.drop_index("ix_match_participants_team_id", table_name="match_participants")
    op.drop_index("ix_match_participants_match_id", table_name="match_participants")
    op.drop_table("match_participants")

    bind = op.get_bind()
    postgresql.ENUM(name="match_check_in_status").drop(bind, checkfirst=True)
    postgresql.ENUM(name="match_assignment_type").drop(bind, checkfirst=True)

    op.drop_index("ix_matches_tournament_round", table_name="matches")
    op.drop_index("ix_matches_tournament_status", table_name="matches")
    op.drop_index("ix_matches_created_by", table_name="matches")
    op.drop_index("ix_matches_winner_team_id", table_name="matches")
    op.drop_index("ix_matches_match_status", table_name="matches")
    op.drop_index("ix_matches_room_status", table_name="matches")
    op.drop_index("ix_matches_tournament_id", table_name="matches")
    op.drop_index("ix_matches_match_uid", table_name="matches")
    op.drop_table("matches")

    postgresql.ENUM(name="match_status").drop(bind, checkfirst=True)
    postgresql.ENUM(name="match_room_status").drop(bind, checkfirst=True)
