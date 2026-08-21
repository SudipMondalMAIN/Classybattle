"""add duo/free to home_category_box_type enum

Revision ID: 0041_box_duo_free
Revises: 0040_prize_type
Create Date: 2026-08-21

Home-screen "Browse Tournaments" boxes could only be solo/squad/custom.
Adds duo and free so Admin can create e.g. "Free Fire Duo" and
"Free Fire Free Entry" boxes -- same game_id-required rule as
solo/squad (only custom stays game_id-less), no schema/constraint
change needed since the existing check constraint is already
`box_type != 'custom' -> game_id required`.
"""
from alembic import op

# revision identifiers, used by Alembic.
revision = "0041_box_duo_free"
down_revision = "0040_prize_type"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Postgres requires ALTER TYPE ... ADD VALUE to run outside an
    # explicit transaction block in older versions; alembic runs
    # migrations inside a transaction by default, so this must be
    # committed immediately before anything else can use the new value
    # in the same migration run.
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE home_category_box_type ADD VALUE IF NOT EXISTS 'duo'")
        op.execute("ALTER TYPE home_category_box_type ADD VALUE IF NOT EXISTS 'free'")


def downgrade() -> None:
    # Postgres doesn't support removing enum values directly. Leaving
    # this a no-op is safe: any existing 'duo'/'free' rows would need
    # to be migrated to another box_type by a data migration before a
    # real downgrade, which is out of scope for a value-add migration.
    pass