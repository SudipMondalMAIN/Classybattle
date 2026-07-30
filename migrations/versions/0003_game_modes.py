"""game modes - phase 3

Revision ID: 0003_game_modes
Revises: 0002_tournaments
Create Date: 2026-07-30

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003_game_modes"
down_revision: Union[str, None] = "0002_tournaments"
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
    op.create_table(
        "game_modes",
        *_base_columns(),
        sa.Column("mode_uid", sa.String(20), nullable=False),
        sa.Column(
            "game_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("games.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("slug", sa.String(130), nullable=False),
        sa.Column("short_name", sa.String(30), nullable=True),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("icon_url", sa.String(500), nullable=True),
        sa.Column("image_url", sa.String(500), nullable=True),
        sa.Column("max_team_size", sa.Integer, nullable=False, server_default="1"),
        sa.Column("min_players", sa.Integer, nullable=False, server_default="1"),
        sa.Column("max_players", sa.Integer, nullable=False, server_default="1"),
        sa.Column("sort_order", sa.Integer, nullable=False, server_default="0"),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("is_featured", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column(
            "created_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "updated_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.UniqueConstraint("mode_uid", name="uq_game_modes_mode_uid"),
        sa.UniqueConstraint("game_id", "slug", name="uq_game_modes_game_id_slug"),
        sa.UniqueConstraint("game_id", "name", name="uq_game_modes_game_id_name"),
        sa.CheckConstraint("min_players > 0", name="ck_game_modes_min_players_positive"),
        sa.CheckConstraint("max_players >= min_players", name="ck_game_modes_max_ge_min_players"),
        sa.CheckConstraint("max_team_size > 0", name="ck_game_modes_max_team_size_positive"),
    )

    op.create_index("ix_game_modes_mode_uid", "game_modes", ["mode_uid"])
    op.create_index("ix_game_modes_game_id", "game_modes", ["game_id"])
    op.create_index("ix_game_modes_slug", "game_modes", ["slug"])
    op.create_index("ix_game_modes_sort_order", "game_modes", ["sort_order"])
    op.create_index("ix_game_modes_is_active", "game_modes", ["is_active"])
    op.create_index("ix_game_modes_created_by", "game_modes", ["created_by"])
    op.create_index("ix_game_modes_game_active", "game_modes", ["game_id", "is_active"])
    op.create_index("ix_game_modes_game_featured", "game_modes", ["game_id", "is_featured"])


def downgrade() -> None:
    op.drop_index("ix_game_modes_game_featured", table_name="game_modes")
    op.drop_index("ix_game_modes_game_active", table_name="game_modes")
    op.drop_index("ix_game_modes_created_by", table_name="game_modes")
    op.drop_index("ix_game_modes_is_active", table_name="game_modes")
    op.drop_index("ix_game_modes_sort_order", table_name="game_modes")
    op.drop_index("ix_game_modes_slug", table_name="game_modes")
    op.drop_index("ix_game_modes_game_id", table_name="game_modes")
    op.drop_index("ix_game_modes_mode_uid", table_name="game_modes")
    op.drop_table("game_modes")
