"""tournament core - phase 2

Revision ID: 0002_tournaments
Revises: 0001_initial
Create Date: 2026-07-30

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002_tournaments"
down_revision: Union[str, None] = "0001_initial"
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
    tournament_status = postgresql.ENUM(
        "draft",
        "published",
        "registration_open",
        "registration_closed",
        "live",
        "completed",
        "archived",
        "cancelled",
        name="tournament_status",
        create_type=False,
    )
    tournament_visibility = postgresql.ENUM(
        "public", "private", "unlisted", name="tournament_visibility", create_type=False
    )

    bind = op.get_bind()
    tournament_status.create(bind, checkfirst=True)
    tournament_visibility.create(bind, checkfirst=True)

    op.create_table(
        "tournaments",
        *_base_columns(),
        sa.Column("tournament_uid", sa.String(20), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("slug", sa.String(230), nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column(
            "game_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("games.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("mode_id", sa.String(50), nullable=True),
        sa.Column("map_id", sa.String(50), nullable=True),
        sa.Column("banner_url", sa.String(500), nullable=True),
        sa.Column("cover_url", sa.String(500), nullable=True),
        sa.Column("organizer", sa.String(150), nullable=False),
        sa.Column("entry_fee", sa.Numeric(10, 2), nullable=False, server_default="0"),
        sa.Column("prize_pool", sa.Numeric(12, 2), nullable=False, server_default="0"),
        sa.Column("max_players", sa.Integer, nullable=False),
        sa.Column("current_players", sa.Integer, nullable=False, server_default="0"),
        sa.Column("registration_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("registration_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("tournament_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("tournament_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", tournament_status, nullable=False, server_default="draft"),
        sa.Column(
            "visibility", tournament_visibility, nullable=False, server_default="public"
        ),
        sa.Column("is_featured", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column(
            "created_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.UniqueConstraint("tournament_uid", name="uq_tournaments_tournament_uid"),
        sa.UniqueConstraint("slug", name="uq_tournaments_slug"),
        sa.CheckConstraint("entry_fee >= 0", name="ck_tournaments_entry_fee_non_negative"),
        sa.CheckConstraint("prize_pool >= 0", name="ck_tournaments_prize_pool_non_negative"),
        sa.CheckConstraint("max_players > 0", name="ck_tournaments_max_players_positive"),
        sa.CheckConstraint(
            "current_players >= 0 AND current_players <= max_players",
            name="ck_tournaments_current_players_within_bounds",
        ),
        sa.CheckConstraint(
            "registration_end > registration_start",
            name="ck_tournaments_registration_window_valid",
        ),
        sa.CheckConstraint(
            "tournament_end > tournament_start", name="ck_tournaments_play_window_valid"
        ),
    )

    op.create_index("ix_tournaments_tournament_uid", "tournaments", ["tournament_uid"])
    op.create_index("ix_tournaments_slug", "tournaments", ["slug"])
    op.create_index("ix_tournaments_game_id", "tournaments", ["game_id"])
    op.create_index("ix_tournaments_status", "tournaments", ["status"])
    op.create_index("ix_tournaments_created_by", "tournaments", ["created_by"])
    op.create_index(
        "ix_tournaments_status_visibility", "tournaments", ["status", "visibility"]
    )
    op.create_index("ix_tournaments_game_status", "tournaments", ["game_id", "status"])


def downgrade() -> None:
    op.drop_index("ix_tournaments_game_status", table_name="tournaments")
    op.drop_index("ix_tournaments_status_visibility", table_name="tournaments")
    op.drop_index("ix_tournaments_created_by", table_name="tournaments")
    op.drop_index("ix_tournaments_status", table_name="tournaments")
    op.drop_index("ix_tournaments_game_id", table_name="tournaments")
    op.drop_index("ix_tournaments_slug", table_name="tournaments")
    op.drop_index("ix_tournaments_tournament_uid", table_name="tournaments")
    op.drop_table("tournaments")

    bind = op.get_bind()
    postgresql.ENUM(name="tournament_visibility").drop(bind, checkfirst=True)
    postgresql.ENUM(name="tournament_status").drop(bind, checkfirst=True)
