"""continuous slot numbering for recurring schedules

Revision ID: 0052_schedule_slot_running_number
Revises: 0051_support_chat_media
Create Date: 2026-09-07

Adds `last_slot_number` to tournaments: a running counter kept on each
recurring-schedule template row so generated slot titles (`Title #1`,
`#2`, ...) number up continuously across days instead of resetting to
#1 every day. E.g. with 13 daily_slot_times: day 1 generates #1-#13,
day 2 generates #14-#26, day 3 #27-#39, and so on indefinitely.

Backfill: existing schedule templates start at 0 (nullable-safe
default), so their *next* generation continues from wherever their
already-generated slots left off is NOT automatically inferred here --
operators should set last_slot_number to the correct current max via a
one-off update if they want continuity to pick up mid-stream; fresh
schedules and schedules that haven't generated any slots yet are
unaffected and simply start at #1 as before.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0052_schedule_slot_running_number"
down_revision: Union[str, None] = "0051_support_chat_media"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "tournaments",
        sa.Column(
            "last_slot_number",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )
    # Drop the server_default after backfilling existing rows so future
    # inserts must go through the ORM default (matches project convention
    # for other non-null columns added post-hoc).
    op.alter_column("tournaments", "last_slot_number", server_default=None)


def downgrade() -> None:
    op.drop_column("tournaments", "last_slot_number")