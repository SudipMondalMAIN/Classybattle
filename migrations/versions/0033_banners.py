"""add banners table for home-screen promo banners

Revision ID: 0033_banners
Revises: 0032_winner_rank
Create Date: 2026-08-10

Admin panel manages these: direct image upload (via Supabase storage),
with optional title + redirect link + sort order + active flag.
"""
import uuid

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "0033_banners"
down_revision = "0032_winner_rank"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "banners",
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
        sa.Column("image_url", sa.Text(), nullable=False),
        sa.Column("title", sa.String(length=150), nullable=True),
        sa.Column("redirect_link", sa.String(length=500), nullable=True),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    op.create_index("ix_banners_sort_order", "banners", ["sort_order"])
    op.create_index("ix_banners_is_active", "banners", ["is_active"])


def downgrade() -> None:
    op.drop_index("ix_banners_is_active", table_name="banners")
    op.drop_index("ix_banners_sort_order", table_name="banners")
    op.drop_table("banners")
