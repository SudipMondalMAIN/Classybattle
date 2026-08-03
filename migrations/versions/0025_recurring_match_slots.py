"""recurring match slots - Free Fire / BGMI tournament overhaul

Revision ID: 0025_recurring_match_slots
Revises: 0024_leaderboard
Create Date: 2026-08-03

Adds support for recurring, time-slotted matches (e.g. Free Fire /
BGMI matches every 20-30 minutes from 10AM-11PM) on top of the
existing bracket-tournament schema, instead of replacing it:

- tournaments: is_recurring_schedule + daily_start_time/daily_end_time
  + slot_interval_minutes + allowed_team_formats + last_generated_on,
  so a Tournament row can act as a recurring schedule template that
  SlotGeneratorService stamps into Match rows.
- matches: team_format + entry_fee, so each generated slot carries its
  own join-time settings independent of the parent schedule.
- match_teams / match_team_members: per-slot teams for Clash-Squad
  style 1v1/2v2/3v3/4v4 formats (distinct from `teams`, which is
  scoped to a whole tournament and only allows one team per user).
- match_participants: match_team_id, so a slot can be occupied by a
  MatchTeam in addition to the existing Team/Participant options.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0025_recurring_match_slots"
down_revision: Union[str, None] = "0024_leaderboard"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ------------------------------------------------------------------
    # tournaments: recurring schedule config
    # ------------------------------------------------------------------
    op.add_column(
        "tournaments",
        sa.Column(
            "is_recurring_schedule", sa.Boolean(), server_default="false", nullable=False
        ),
    )
    op.add_column("tournaments", sa.Column("daily_start_time", sa.Time(), nullable=True))
    op.add_column("tournaments", sa.Column("daily_end_time", sa.Time(), nullable=True))
    op.add_column(
        "tournaments", sa.Column("slot_interval_minutes", sa.Integer(), nullable=True)
    )
    op.add_column(
        "tournaments",
        sa.Column(
            "allowed_team_formats",
            postgresql.JSONB().with_variant(sa.JSON(), "sqlite"),
            nullable=True,
        ),
    )
    op.add_column(
        "tournaments",
        sa.Column("last_generated_on", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_tournaments_is_recurring_schedule", "tournaments", ["is_recurring_schedule"]
    )

    # ------------------------------------------------------------------
    # matches: per-slot format & fee
    # ------------------------------------------------------------------
    op.add_column("matches", sa.Column("team_format", sa.String(length=10), nullable=True))
    op.add_column("matches", sa.Column("entry_fee", sa.Numeric(10, 2), nullable=True))

    # ------------------------------------------------------------------
    # match_teams
    # ------------------------------------------------------------------
    op.create_table(
        "match_teams",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("match_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("team_name", sa.String(length=150), nullable=True),
        sa.Column("captain_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("invite_code", sa.String(length=16), nullable=False),
        sa.Column("team_format", sa.String(length=10), nullable=False),
        sa.Column("team_size", sa.Integer(), nullable=False),
        sa.Column("current_members", sa.Integer(), server_default="0", nullable=False),
        sa.Column("is_random", sa.Boolean(), server_default="false", nullable=False),
        sa.Column(
            "status",
            sa.Enum("forming", "locked", "disbanded", name="match_team_status"),
            server_default="forming",
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["match_id"], ["matches.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["captain_id"], ["users.id"], ondelete="SET NULL"),
        sa.UniqueConstraint("invite_code", name="uq_match_teams_invite_code"),
        sa.CheckConstraint("team_size > 0", name="ck_match_teams_team_size_positive"),
        sa.CheckConstraint(
            "current_members >= 0 AND current_members <= team_size",
            name="ck_match_teams_current_members_within_bounds",
        ),
    )
    op.create_index("ix_match_teams_match_id", "match_teams", ["match_id"])
    op.create_index("ix_match_teams_captain_id", "match_teams", ["captain_id"])
    op.create_index("ix_match_teams_invite_code", "match_teams", ["invite_code"])
    op.create_index("ix_match_teams_status", "match_teams", ["status"])
    op.create_index("ix_match_teams_is_random", "match_teams", ["is_random"])
    op.create_index("ix_match_teams_match_status", "match_teams", ["match_id", "status"])

    # ------------------------------------------------------------------
    # match_team_members
    # ------------------------------------------------------------------
    op.create_table(
        "match_team_members",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("match_team_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.ForeignKeyConstraint(["match_team_id"], ["match_teams.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.UniqueConstraint(
            "match_team_id", "user_id", name="uq_match_team_members_team_user"
        ),
    )
    op.create_index("ix_match_team_members_match_team_id", "match_team_members", ["match_team_id"])
    op.create_index("ix_match_team_members_user_id", "match_team_members", ["user_id"])

    # ------------------------------------------------------------------
    # match_participants: allow a slot to point at a MatchTeam
    # ------------------------------------------------------------------
    op.add_column(
        "match_participants",
        sa.Column("match_team_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_match_participants_match_team_id",
        "match_participants",
        "match_teams",
        ["match_team_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_index(
        "ix_match_participants_match_team_id", "match_participants", ["match_team_id"]
    )
    op.drop_constraint(
        "ck_match_participants_team_or_participant", "match_participants", type_="check"
    )
    op.create_check_constraint(
        "ck_match_participants_team_or_participant",
        "match_participants",
        "(team_id IS NOT NULL) OR (participant_id IS NOT NULL) OR (match_team_id IS NOT NULL)",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_match_participants_team_or_participant", "match_participants", type_="check"
    )
    op.create_check_constraint(
        "ck_match_participants_team_or_participant",
        "match_participants",
        "(team_id IS NOT NULL) OR (participant_id IS NOT NULL)",
    )
    op.drop_index("ix_match_participants_match_team_id", table_name="match_participants")
    op.drop_constraint(
        "fk_match_participants_match_team_id", "match_participants", type_="foreignkey"
    )
    op.drop_column("match_participants", "match_team_id")

    op.drop_index("ix_match_team_members_user_id", table_name="match_team_members")
    op.drop_index("ix_match_team_members_match_team_id", table_name="match_team_members")
    op.drop_table("match_team_members")

    op.drop_index("ix_match_teams_match_status", table_name="match_teams")
    op.drop_index("ix_match_teams_is_random", table_name="match_teams")
    op.drop_index("ix_match_teams_status", table_name="match_teams")
    op.drop_index("ix_match_teams_invite_code", table_name="match_teams")
    op.drop_index("ix_match_teams_captain_id", table_name="match_teams")
    op.drop_index("ix_match_teams_match_id", table_name="match_teams")
    op.drop_table("match_teams")
    sa.Enum(name="match_team_status").drop(op.get_bind(), checkfirst=True)

    op.drop_column("matches", "entry_fee")
    op.drop_column("matches", "team_format")

    op.drop_index("ix_tournaments_is_recurring_schedule", table_name="tournaments")
    op.drop_column("tournaments", "last_generated_on")
    op.drop_column("tournaments", "allowed_team_formats")
    op.drop_column("tournaments", "slot_interval_minutes")
    op.drop_column("tournaments", "daily_end_time")
    op.drop_column("tournaments", "daily_start_time")
    op.drop_column("tournaments", "is_recurring_schedule")
