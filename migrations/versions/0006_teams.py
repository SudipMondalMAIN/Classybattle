"""team system & invite management - phase 6

Revision ID: 0006_teams
Revises: 0005_participants
Create Date: 2026-07-30

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0006_teams"
down_revision: Union[str, None] = "0005_participants"
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
    # Tournament: team registration settings
    # ------------------------------------------------------------------
    registration_mode = postgresql.ENUM(
        "solo", "team_invite", "auto_random", name="tournament_registration_mode", create_type=False
    )
    registration_mode.create(bind, checkfirst=True)

    op.add_column(
        "tournaments",
        sa.Column(
            "registration_mode",
            registration_mode,
            nullable=False,
            server_default="solo",
        ),
    )
    op.add_column(
        "tournaments",
        sa.Column("team_size", sa.Integer(), nullable=False, server_default="1"),
    )
    op.add_column(
        "tournaments",
        sa.Column("max_teams", sa.Integer(), nullable=True),
    )
    op.create_check_constraint(
        "ck_tournaments_team_size_positive", "tournaments", "team_size > 0"
    )
    op.create_check_constraint(
        "ck_tournaments_max_teams_positive",
        "tournaments",
        "max_teams IS NULL OR max_teams > 0",
    )

    # ------------------------------------------------------------------
    # teams
    # ------------------------------------------------------------------
    team_status = postgresql.ENUM("forming", "locked", "disbanded", name="team_status", create_type=False)
    team_status.create(bind, checkfirst=True)

    op.create_table(
        "teams",
        *_base_columns(),
        sa.Column("team_uid", sa.String(20), nullable=False),
        sa.Column(
            "tournament_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tournaments.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("team_name", sa.String(150), nullable=False),
        sa.Column(
            "captain_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("invite_code", sa.String(16), nullable=False),
        sa.Column("team_size", sa.Integer(), nullable=False),
        sa.Column("current_members", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("status", team_status, nullable=False, server_default="forming"),
        sa.Column("is_locked", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.UniqueConstraint("team_uid", name="uq_teams_team_uid"),
        sa.UniqueConstraint("invite_code", name="uq_teams_invite_code"),
        sa.UniqueConstraint("tournament_id", "team_name", name="uq_teams_tournament_team_name"),
        sa.CheckConstraint("team_size > 0", name="ck_teams_team_size_positive"),
        sa.CheckConstraint(
            "current_members >= 0 AND current_members <= team_size",
            name="ck_teams_current_members_within_bounds",
        ),
    )

    op.create_index("ix_teams_team_uid", "teams", ["team_uid"])
    op.create_index("ix_teams_tournament_id", "teams", ["tournament_id"])
    op.create_index("ix_teams_captain_id", "teams", ["captain_id"])
    op.create_index("ix_teams_invite_code", "teams", ["invite_code"])
    op.create_index("ix_teams_status", "teams", ["status"])
    op.create_index("ix_teams_tournament_status", "teams", ["tournament_id", "status"])

    # ------------------------------------------------------------------
    # team_members
    # ------------------------------------------------------------------
    team_member_role = postgresql.ENUM("captain", "member", name="team_member_role", create_type=False)
    team_member_role.create(bind, checkfirst=True)

    op.create_table(
        "team_members",
        *_base_columns(),
        sa.Column(
            "team_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("teams.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "participant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("participants.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("role", team_member_role, nullable=False, server_default="member"),
        sa.Column("joined_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("team_id", "user_id", name="uq_team_members_team_user"),
    )

    op.create_index("ix_team_members_team_id", "team_members", ["team_id"])
    op.create_index("ix_team_members_user_id", "team_members", ["user_id"])
    op.create_index("ix_team_members_participant_id", "team_members", ["participant_id"])
    op.create_index("ix_team_members_team_role", "team_members", ["team_id", "role"])


def downgrade() -> None:
    op.drop_index("ix_team_members_team_role", table_name="team_members")
    op.drop_index("ix_team_members_participant_id", table_name="team_members")
    op.drop_index("ix_team_members_user_id", table_name="team_members")
    op.drop_index("ix_team_members_team_id", table_name="team_members")
    op.drop_table("team_members")

    op.drop_index("ix_teams_tournament_status", table_name="teams")
    op.drop_index("ix_teams_status", table_name="teams")
    op.drop_index("ix_teams_invite_code", table_name="teams")
    op.drop_index("ix_teams_captain_id", table_name="teams")
    op.drop_index("ix_teams_tournament_id", table_name="teams")
    op.drop_index("ix_teams_team_uid", table_name="teams")
    op.drop_table("teams")

    bind = op.get_bind()
    postgresql.ENUM(name="team_member_role").drop(bind, checkfirst=True)
    postgresql.ENUM(name="team_status").drop(bind, checkfirst=True)

    op.drop_constraint("ck_tournaments_max_teams_positive", "tournaments", type_="check")
    op.drop_constraint("ck_tournaments_team_size_positive", "tournaments", type_="check")
    op.drop_column("tournaments", "max_teams")
    op.drop_column("tournaments", "team_size")
    op.drop_column("tournaments", "registration_mode")
    postgresql.ENUM(name="tournament_registration_mode").drop(bind, checkfirst=True)
