"""add home_category_boxes table for home-screen tap boxes

Revision ID: 0034_home_category_boxes
Revises: 0033_banners
Create Date: 2026-08-14

Admin panel manages these: pick box_type (solo/squad/custom), a game
(required unless custom), a banner image link, optional title, sort
order and active flag. Rendered on the app home screen 3-per-row with
the same card design as a live tournament card, but fully static.
"""
import uuid

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "0034_home_category_boxes"
down_revision = "0033_banners"
branch_labels = None
depends_on = None


def upgrade() -> None:
    home_category_box_type = postgresql.ENUM(
        "solo", "squad", "custom", name="home_category_box_type", create_type=False
    )
    bind = op.get_bind()
    home_category_box_type.create(bind, checkfirst=True)

    op.create_table(
        "home_category_boxes",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            default=uuid.uuid4,
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("box_type", home_category_box_type, nullable=False),
        sa.Column(
            "game_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("games.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("banner_url", sa.String(length=500), nullable=False),
        sa.Column("title", sa.String(length=150), nullable=True),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.CheckConstraint(
            "(box_type = 'custom' AND game_id IS NULL) OR "
            "(box_type != 'custom' AND game_id IS NOT NULL)",
            name="ck_home_category_boxes_game_required_unless_custom",
        ),
    )
    op.create_index("ix_home_category_boxes_box_type", "home_category_boxes", ["box_type"])
    op.create_index("ix_home_category_boxes_game_id", "home_category_boxes", ["game_id"])
    op.create_index("ix_home_category_boxes_sort_order", "home_category_boxes", ["sort_order"])
    op.create_index("ix_home_category_boxes_is_active", "home_category_boxes", ["is_active"])


def downgrade() -> None:
    op.drop_index("ix_home_category_boxes_is_active", table_name="home_category_boxes")
    op.drop_index("ix_home_category_boxes_sort_order", table_name="home_category_boxes")
    op.drop_index("ix_home_category_boxes_game_id", table_name="home_category_boxes")
    op.drop_index("ix_home_category_boxes_box_type", table_name="home_category_boxes")
    op.drop_table("home_category_boxes")

    bind = op.get_bind()
    postgresql.ENUM(name="home_category_box_type").drop(bind, checkfirst=True)
