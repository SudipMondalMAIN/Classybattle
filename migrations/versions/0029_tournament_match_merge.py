"""remove Match layer, merge into Tournament

Revision ID: 0029_tournament_match_merge
Revises: 0028_otp_signup_payload
Create Date: 2026-08-05

Match-refactor: Tournament itself becomes the joinable/playable unit.
This is a pre-launch, breaking schema change (no production data to
preserve) — the old `matches` / `live_matches` / `match_*` tables are
dropped outright rather than migrated row-by-row, and the surviving
concepts (participants, teams, results, winners) are recreated under
`tournament_*` names, keyed on `tournament_id` instead of `match_id`.

- Drop: matches, match_participants, match_teams, match_team_members,
  match_results, match_winners, live_matches, live_match_events,
  live_match_scores, live_tournament_states (+ their now-unused enums)
- tournaments: drop registration/play window columns + constraints,
  add room_id/room_password/published_at/auto_complete_at, collapse
  status enum down to scheduled/live/completed/cancelled
- Create: tournament_teams, tournament_team_members,
  tournament_participants, tournament_results, tournament_winners
  (same shape as their match_* predecessors, FK'd to tournaments)
- moderation_reports.target_type: "match" -> "tournament"
- activity_feed_entries.activity_type: add "tournament_played"
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "0029_tournament_match_merge"
down_revision = "0028_otp_signup_payload"
branch_labels = None
depends_on = None


def _base_columns():
    return [
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False, unique=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    ]


def upgrade() -> None:
    bind = op.get_bind()

    # ------------------------------------------------------------------
    # 1) Drop the Match layer outright (dependency order matters).
    # ------------------------------------------------------------------
    op.drop_table("match_winners")
    op.drop_table("match_results")
    op.drop_table("live_tournament_states")
    op.drop_table("live_match_scores")
    op.drop_table("live_match_events")
    op.drop_table("live_matches")
    op.drop_table("match_participants")
    op.drop_table("match_team_members")
    op.drop_table("match_teams")
    op.drop_table("matches")

    for enum_name in (
        "match_result_status",
        "match_status",
        "match_room_status",
        "match_assignment_type",
        "match_check_in_status",
        "live_match_status",
        "live_match_event_type",
        "live_tournament_status",
        "match_team_status",
    ):
        postgresql.ENUM(name=enum_name).drop(bind, checkfirst=True)
    # winner_assignment_source is NOT dropped — tournament_winners (below)
    # reuses it unchanged.

    # ------------------------------------------------------------------
    # 2) tournaments: drop registration/play windows, add room/live info,
    #    collapse status enum to the 4-value Tournament lifecycle.
    # ------------------------------------------------------------------
    op.drop_constraint("ck_tournaments_registration_window_valid", "tournaments", type_="check")
    op.drop_constraint("ck_tournaments_play_window_valid", "tournaments", type_="check")
    op.drop_column("tournaments", "registration_start")
    op.drop_column("tournaments", "registration_end")
    op.drop_column("tournaments", "tournament_start")
    op.drop_column("tournaments", "tournament_end")

    op.add_column("tournaments", sa.Column("room_id", sa.String(100), nullable=True))
    op.add_column("tournaments", sa.Column("room_password", sa.String(100), nullable=True))
    op.add_column("tournaments", sa.Column("published_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("tournaments", sa.Column("auto_complete_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index(
        "ix_tournaments_status_auto_complete", "tournaments", ["status", "auto_complete_at"]
    )

    # Old enum had 8 values (draft/published/registration_open/
    # registration_closed/live/completed/archived/cancelled). Map every
    # existing row down to the new 4-value set, then swap the type.
    op.execute(
        "ALTER TABLE tournaments ALTER COLUMN status DROP DEFAULT"
    )
    op.execute("ALTER TYPE tournament_status RENAME TO tournament_status_old")
    tournament_status_new = postgresql.ENUM(
        "scheduled", "live", "completed", "cancelled", name="tournament_status"
    )
    tournament_status_new.create(bind, checkfirst=True)
    op.execute(
        """
        ALTER TABLE tournaments
        ALTER COLUMN status TYPE tournament_status
        USING (
            CASE status::text
                WHEN 'draft' THEN 'scheduled'
                WHEN 'published' THEN 'scheduled'
                WHEN 'registration_open' THEN 'scheduled'
                WHEN 'registration_closed' THEN 'scheduled'
                WHEN 'live' THEN 'live'
                WHEN 'completed' THEN 'completed'
                WHEN 'archived' THEN 'completed'
                WHEN 'cancelled' THEN 'cancelled'
                ELSE 'scheduled'
            END
        )::tournament_status
        """
    )
    op.execute("ALTER TABLE tournaments ALTER COLUMN status SET DEFAULT 'scheduled'")
    postgresql.ENUM(name="tournament_status_old").drop(bind, checkfirst=True)

    # ------------------------------------------------------------------
    # 3) tournament_teams / tournament_team_members
    #    (formerly match_teams / match_team_members)
    # ------------------------------------------------------------------
    op.create_table(
        "tournament_teams",
        *_base_columns(),
        sa.Column("tournament_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("team_name", sa.String(150), nullable=True),
        sa.Column("captain_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("invite_code", sa.String(16), nullable=False),
        sa.Column("team_format", sa.String(10), nullable=False),
        sa.Column("team_size", sa.Integer(), nullable=False),
        sa.Column("current_members", sa.Integer(), server_default="0", nullable=False),
        sa.Column("is_random", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column(
            "status",
            sa.Enum("forming", "locked", "disbanded", name="tournament_team_status"),
            server_default="forming",
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["tournament_id"], ["tournaments.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["captain_id"], ["users.id"], ondelete="SET NULL"),
        sa.UniqueConstraint("invite_code", name="uq_tournament_teams_invite_code"),
        sa.CheckConstraint("team_size > 0", name="ck_tournament_teams_team_size_positive"),
        sa.CheckConstraint(
            "current_members >= 0 AND current_members <= team_size",
            name="ck_tournament_teams_current_members_within_bounds",
        ),
    )
    op.create_index("ix_tournament_teams_tournament_id", "tournament_teams", ["tournament_id"])
    op.create_index("ix_tournament_teams_captain_id", "tournament_teams", ["captain_id"])
    op.create_index("ix_tournament_teams_invite_code", "tournament_teams", ["invite_code"])
    op.create_index("ix_tournament_teams_status", "tournament_teams", ["status"])
    op.create_index("ix_tournament_teams_is_random", "tournament_teams", ["is_random"])
    op.create_index(
        "ix_tournament_teams_tournament_status", "tournament_teams", ["tournament_id", "status"]
    )

    op.create_table(
        "tournament_team_members",
        *_base_columns(),
        sa.Column("tournament_team_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("kills", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("is_winner", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("winning_amount", sa.Numeric(12, 2), nullable=True),
        sa.Column("winning_paid_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["tournament_team_id"], ["tournament_teams.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.UniqueConstraint(
            "tournament_team_id", "user_id", name="uq_tournament_team_members_team_user"
        ),
    )
    op.create_index(
        "ix_tournament_team_members_tournament_team_id",
        "tournament_team_members",
        ["tournament_team_id"],
    )
    op.create_index("ix_tournament_team_members_user_id", "tournament_team_members", ["user_id"])
    op.create_index(
        "ix_tournament_team_members_is_winner", "tournament_team_members", ["is_winner"]
    )

    # ------------------------------------------------------------------
    # 4) tournament_participants (formerly match_participants)
    # ------------------------------------------------------------------
    tournament_assignment_type = postgresql.ENUM(
        "registered", "random", "manual", "auto",
        name="tournament_assignment_type", create_type=False,
    )
    tournament_assignment_type.create(bind, checkfirst=True)
    tournament_check_in_status = postgresql.ENUM(
        "not_open", "pending", "checked_in", "late_checked_in", "no_show",
        name="tournament_check_in_status", create_type=False,
    )
    tournament_check_in_status.create(bind, checkfirst=True)

    op.create_table(
        "tournament_participants",
        *_base_columns(),
        sa.Column("tournament_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("team_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("tournament_team_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("participant_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("slot_number", sa.Integer(), nullable=False),
        sa.Column(
            "assignment_type", tournament_assignment_type, server_default="registered", nullable=False
        ),
        sa.Column("assigned_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "check_in_status", tournament_check_in_status, server_default="not_open", nullable=False
        ),
        sa.Column("checked_in_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("checked_in_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("is_organizer_override", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("is_disqualified", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("disqualified_reason", sa.String(255), nullable=True),
        sa.Column("replaced_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("kills", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("is_winner", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("winning_amount", sa.Numeric(12, 2), nullable=True),
        sa.Column("winning_paid_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["tournament_id"], ["tournaments.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["team_id"], ["teams.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["tournament_team_id"], ["tournament_teams.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["participant_id"], ["participants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["assigned_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["checked_in_by"], ["users.id"], ondelete="SET NULL"),
        sa.UniqueConstraint(
            "tournament_id", "slot_number", name="uq_tournament_participants_match_slot"
        ),
        sa.UniqueConstraint(
            "tournament_id", "team_id", name="uq_tournament_participants_match_team"
        ),
        sa.UniqueConstraint(
            "tournament_id", "participant_id", name="uq_tournament_participants_match_participant"
        ),
        sa.CheckConstraint("slot_number > 0", name="ck_tournament_participants_slot_positive"),
        sa.CheckConstraint(
            "(team_id IS NOT NULL) OR (participant_id IS NOT NULL) OR (tournament_team_id IS NOT NULL)",
            name="ck_tournament_participants_team_or_participant",
        ),
    )
    op.create_index(
        "ix_tournament_participants_tournament_id", "tournament_participants", ["tournament_id"]
    )
    op.create_index("ix_tournament_participants_team_id", "tournament_participants", ["team_id"])
    op.create_index(
        "ix_tournament_participants_tournament_team_id",
        "tournament_participants",
        ["tournament_team_id"],
    )
    op.create_index(
        "ix_tournament_participants_participant_id", "tournament_participants", ["participant_id"]
    )
    op.create_index(
        "ix_tournament_participants_check_in_status", "tournament_participants", ["check_in_status"]
    )
    op.create_index(
        "ix_tournament_participants_is_winner", "tournament_participants", ["is_winner"]
    )
    op.create_index(
        "ix_tournament_participants_match_checkin",
        "tournament_participants",
        ["tournament_id", "check_in_status"],
    )

    # ------------------------------------------------------------------
    # 5) tournament_results (formerly match_results)
    # ------------------------------------------------------------------
    tournament_result_status = postgresql.ENUM(
        "submitted", "verified", "approved", "rejected",
        name="tournament_result_status", create_type=False,
    )
    tournament_result_status.create(bind, checkfirst=True)

    op.create_table(
        "tournament_results",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("tournament_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("result_data", postgresql.JSONB(), nullable=False),
        sa.Column("is_tie", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("status", tournament_result_status, server_default="submitted", nullable=False),
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
        sa.ForeignKeyConstraint(["tournament_id"], ["tournaments.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["submitted_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["verified_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["approved_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["rejected_by"], ["users.id"], ondelete="SET NULL"),
        sa.UniqueConstraint("tournament_id", name="uq_tournament_results_tournament_id"),
    )
    op.create_index(
        "ix_tournament_results_tournament_id", "tournament_results", ["tournament_id"]
    )
    op.create_index("ix_tournament_results_status", "tournament_results", ["status"])
    op.create_index(
        "ix_tournament_results_tournament_status",
        "tournament_results",
        ["tournament_id", "status"],
    )

    # ------------------------------------------------------------------
    # 6) tournament_winners (formerly match_winners) — reuses the
    #    existing winner_assignment_source enum unchanged.
    # ------------------------------------------------------------------
    winner_assignment_source = postgresql.ENUM(
        "automatic", "manual", name="winner_assignment_source", create_type=False
    )

    op.create_table(
        "tournament_winners",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("tournament_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tournament_result_id", postgresql.UUID(as_uuid=True), nullable=False),
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
        sa.ForeignKeyConstraint(["tournament_id"], ["tournaments.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["tournament_result_id"], ["tournament_results.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["team_id"], ["teams.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["participant_id"], ["participants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["declared_by"], ["users.id"], ondelete="SET NULL"),
        sa.UniqueConstraint(
            "tournament_id", "rank", "team_id", name="uq_tournament_winners_tournament_rank_team"
        ),
        sa.UniqueConstraint(
            "tournament_id", "rank", "participant_id",
            name="uq_tournament_winners_tournament_rank_participant",
        ),
        sa.UniqueConstraint(
            "tournament_id", "team_id", name="uq_tournament_winners_tournament_team"
        ),
        sa.UniqueConstraint(
            "tournament_id", "participant_id", name="uq_tournament_winners_tournament_participant"
        ),
        sa.CheckConstraint("rank > 0", name="ck_tournament_winners_rank_positive"),
        sa.CheckConstraint(
            "(team_id IS NOT NULL) OR (participant_id IS NOT NULL)",
            name="ck_tournament_winners_team_or_participant",
        ),
    )
    op.create_index(
        "ix_tournament_winners_tournament_id", "tournament_winners", ["tournament_id"]
    )
    op.create_index(
        "ix_tournament_winners_tournament_result_id", "tournament_winners", ["tournament_result_id"]
    )
    op.create_index("ix_tournament_winners_team_id", "tournament_winners", ["team_id"])
    op.create_index(
        "ix_tournament_winners_participant_id", "tournament_winners", ["participant_id"]
    )
    op.create_index(
        "ix_tournament_winners_tournament_rank", "tournament_winners", ["tournament_id", "rank"]
    )

    # ------------------------------------------------------------------
    # 7) moderation_reports.target_type: "match" -> "tournament"
    # ------------------------------------------------------------------
    op.execute("ALTER TYPE report_target_type RENAME VALUE 'match' TO 'tournament'")

    # ------------------------------------------------------------------
    # 8) activity_feed_entries.activity_type: add "tournament_played".
    #    ("match_played"/"match_won" values are left in the enum type
    #    since Postgres cannot drop enum values in place; the model no
    #    longer emits them.)
    # ------------------------------------------------------------------
    op.execute("ALTER TYPE activity_type ADD VALUE IF NOT EXISTS 'tournament_played'")


def downgrade() -> None:
    # This refactor is not meaningfully reversible (the Match layer's
    # bracket/round semantics are gone for good), so downgrade only
    # restores the tournaments columns/enum and drops the new tables —
    # it does not recreate matches/live_matches.
    op.execute("ALTER TYPE report_target_type RENAME VALUE 'tournament' TO 'match'")

    op.drop_table("tournament_winners")
    op.drop_table("tournament_results")
    postgresql.ENUM(name="tournament_result_status").drop(op.get_bind(), checkfirst=True)

    op.drop_table("tournament_participants")
    postgresql.ENUM(name="tournament_check_in_status").drop(op.get_bind(), checkfirst=True)
    postgresql.ENUM(name="tournament_assignment_type").drop(op.get_bind(), checkfirst=True)

    op.drop_table("tournament_team_members")
    op.drop_table("tournament_teams")
    postgresql.ENUM(name="tournament_team_status").drop(op.get_bind(), checkfirst=True)

    bind = op.get_bind()
    op.execute("ALTER TABLE tournaments ALTER COLUMN status DROP DEFAULT")
    op.execute("ALTER TYPE tournament_status RENAME TO tournament_status_new")
    tournament_status_old = postgresql.ENUM(
        "draft", "published", "registration_open", "registration_closed",
        "live", "completed", "archived", "cancelled", name="tournament_status",
    )
    tournament_status_old.create(bind, checkfirst=True)
    op.execute(
        """
        ALTER TABLE tournaments
        ALTER COLUMN status TYPE tournament_status
        USING (
            CASE status::text
                WHEN 'scheduled' THEN 'draft'
                WHEN 'live' THEN 'live'
                WHEN 'completed' THEN 'completed'
                WHEN 'cancelled' THEN 'cancelled'
                ELSE 'draft'
            END
        )::tournament_status
        """
    )
    op.execute("ALTER TABLE tournaments ALTER COLUMN status SET DEFAULT 'draft'")
    postgresql.ENUM(name="tournament_status_new").drop(bind, checkfirst=True)

    op.drop_index("ix_tournaments_status_auto_complete", table_name="tournaments")
    op.drop_column("tournaments", "auto_complete_at")
    op.drop_column("tournaments", "published_at")
    op.drop_column("tournaments", "room_password")
    op.drop_column("tournaments", "room_id")

    op.add_column(
        "tournaments", sa.Column("registration_start", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "tournaments", sa.Column("registration_end", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "tournaments", sa.Column("tournament_start", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "tournaments", sa.Column("tournament_end", sa.DateTime(timezone=True), nullable=True)
    )
    op.create_check_constraint(
        "ck_tournaments_registration_window_valid",
        "tournaments",
        "registration_end IS NULL OR registration_start IS NULL OR registration_end > registration_start",
    )
    op.create_check_constraint(
        "ck_tournaments_play_window_valid",
        "tournaments",
        "tournament_end IS NULL OR tournament_start IS NULL OR tournament_end > tournament_start",
    )
