"""maps - phase 4

Revision ID: 0004_maps
Revises: 0003_game_modes
Create Date: 2026-07-30

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0004_maps"
down_revision: Union[str, None] = "0003_game_modes"
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
        "maps",
        *_base_columns(),
        sa.Column("map_uid", sa.String(20), nullable=False),
        sa.Column(
            "game_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("games.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "mode_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("game_modes.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("slug", sa.String(130), nullable=False),
        sa.Column("short_name", sa.String(30), nullable=True),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("image_url", sa.String(500), nullable=True),
        sa.Column("thumbnail_url", sa.String(500), nullable=True),
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
        sa.UniqueConstraint("map_uid", name="uq_maps_map_uid"),
        sa.UniqueConstraint("game_id", "mode_id", "slug", name="uq_maps_game_id_mode_id_slug"),
        sa.UniqueConstraint("game_id", "mode_id", "name", name="uq_maps_game_id_mode_id_name"),
    )

    op.create_index("ix_maps_map_uid", "maps", ["map_uid"])
    op.create_index("ix_maps_game_id", "maps", ["game_id"])
    op.create_index("ix_maps_mode_id", "maps", ["mode_id"])
    op.create_index("ix_maps_slug", "maps", ["slug"])
    op.create_index("ix_maps_sort_order", "maps", ["sort_order"])
    op.create_index("ix_maps_is_active", "maps", ["is_active"])
    op.create_index("ix_maps_created_by", "maps", ["created_by"])
    op.create_index("ix_maps_game_active", "maps", ["game_id", "is_active"])
    op.create_index("ix_maps_game_featured", "maps", ["game_id", "is_featured"])
    op.create_index("ix_maps_game_mode", "maps", ["game_id", "mode_id"])


def downgrade() -> None:
    op.drop_index("ix_maps_game_mode", table_name="maps")
    op.drop_index("ix_maps_game_featured", table_name="maps")
    op.drop_index("ix_maps_game_active", table_name="maps")
    op.drop_index("ix_maps_created_by", table_name="maps")
    op.drop_index("ix_maps_is_active", table_name="maps")
    op.drop_index("ix_maps_sort_order", table_name="maps")
    op.drop_index("ix_maps_slug", table_name="maps")
    op.drop_index("ix_maps_mode_id", table_name="maps")
    op.drop_index("ix_maps_game_id", table_name="maps")
    op.drop_index("ix_maps_map_uid", table_name="maps")
    op.drop_table("maps")
