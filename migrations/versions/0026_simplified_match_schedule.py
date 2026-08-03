"""simplified solo/squad daily match schedule

Revision ID: 0026_simplified_match_schedule
Revises: 0025_recurring_match_slots
Create Date: 2026-08-03

Simplifies the recurring-schedule flow: Admin no longer creates a
bracket "Tournament" or picks a map/mode. Per Game, Admin configures at
most two schedules — SOLO and SQUAD — each with an admin-editable list
of daily match times (`daily_slot_times`), entry fee, and prize pool.
SlotGeneratorService stamps one Match per time entry per day (count is
not locked to 27 — Admin can add/remove entries freely).

- tournaments: + category (solo/squad), squad_size, daily_slot_times
- matches: + prize_pool (per-match admin override, mirrors entry_fee)
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "0026_simplified_match_schedule"
down_revision = "0025_recurring_match_slots"
branch_labels = None
depends_on = None


def upgrade() -> None:
    schedule_category = postgresql.ENUM(
        "solo", "squad", name="schedule_category", create_type=False
    )
    schedule_category.create(op.get_bind(), checkfirst=True)

    op.add_column(
        "tournaments",
        sa.Column("category", schedule_category, nullable=True),
    )
    op.create_index("ix_tournaments_category", "tournaments", ["category"])
    op.add_column(
        "tournaments",
        sa.Column("squad_size", sa.Integer(), nullable=False, server_default="4"),
    )
    op.add_column(
        "tournaments",
        sa.Column("daily_slot_times", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )

    op.add_column(
        "matches",
        sa.Column("prize_pool", sa.Numeric(12, 2), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("matches", "prize_pool")

    op.drop_column("tournaments", "daily_slot_times")
    op.drop_column("tournaments", "squad_size")
    op.drop_index("ix_tournaments_category", table_name="tournaments")
    op.drop_column("tournaments", "category")

    schedule_category = postgresql.ENUM(
        "solo", "squad", name="schedule_category", create_type=False
    )
    schedule_category.drop(op.get_bind(), checkfirst=True)
