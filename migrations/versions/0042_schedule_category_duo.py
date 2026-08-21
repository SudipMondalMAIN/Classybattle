"""add duo to schedule_category enum

Revision ID: 0042_schedule_category_duo
Revises: 0041_box_duo_free
Create Date: 2026-08-21

Schedules could only be SOLO (join alone) or SQUAD (fixed-size team,
squad_size admin-configurable). Adds DUO as a third category -- a
fixed 2-player-team schedule, same generation/join flow as SQUAD but
with squad_size locked to 2. Same treatment as the home_category_box
duo/free addition in 0041 -- ALTER TYPE ... ADD VALUE must run outside
the migration's transaction block.
"""
from alembic import op

# revision identifiers, used by Alembic.
revision = "0042_schedule_category_duo"
down_revision = "0041_box_duo_free"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE schedule_category ADD VALUE IF NOT EXISTS 'duo'")


def downgrade() -> None:
    # Postgres doesn't support removing enum values directly. Leaving
    # this a no-op is safe: any existing 'duo' schedules/tournaments
    # would need to be migrated to another category by a data migration
    # before a real downgrade, which is out of scope for a value-add
    # migration.
    pass
