"""add free value to schedule_category enum

Revision ID: 0050_free_schedule_category
Revises: 0049_named_format_categories
Create Date: 2026-08-31

home_category_box_type already had 'free' (predates the CS/LW/BR
migration). schedule_category never got it, so Admin has had no way to
create a recurring FREE schedule even though the Free home-screen box
and its "Browse Tournaments" dedicated screen/filter (format=free,
entry_fee==0) already exist end-to-end. Adds 'free' to schedule_category
only -- home_category_box_type already has it.

Postgres requires ALTER TYPE ... ADD VALUE to run outside an explicit
transaction block, so autocommit is used.
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0050_free_schedule_category"
down_revision: Union[str, None] = "0049_named_format_categories"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE schedule_category ADD VALUE IF NOT EXISTS 'free'")


def downgrade() -> None:
    # Postgres has no ALTER TYPE ... DROP VALUE -- see 0049 for the same
    # rationale. Forward-only.
    pass