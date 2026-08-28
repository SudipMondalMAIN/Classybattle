"""add named format categories (CS/LW/BR) to schedule_category and
home_category_box_type enums

Revision ID: 0049_named_format_categories
Revises: 0048_referral_system
Create Date: 2026-08-28

Adds six new values -- cs_1v1, cs_head, cs_4v4, lw_1v1, lw_head,
br_survive -- to both:
- schedule_category (Tournament.category): same join mechanics as
  solo/duo/squad, just a distinct "Browse Tournaments" filter/label.
- home_category_box_type (HomeCategoryBox.box_type): lets Admin create
  a home-screen category box for each of these, same as the existing
  Solo/Squad/Free boxes.

Postgres requires ALTER TYPE ... ADD VALUE to run outside an explicit
transaction block, so autocommit is used for each statement.
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0049_named_format_categories"
down_revision: Union[str, None] = "0048_referral_system"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_NEW_VALUES = ["cs_1v1", "cs_head", "cs_4v4", "lw_1v1", "lw_head", "br_survive"]
_ENUM_TYPES = ["schedule_category", "home_category_box_type"]


def upgrade() -> None:
    with op.get_context().autocommit_block():
        for enum_type in _ENUM_TYPES:
            for value in _NEW_VALUES:
                op.execute(f"ALTER TYPE {enum_type} ADD VALUE IF NOT EXISTS '{value}'")


def downgrade() -> None:
    # Postgres has no ALTER TYPE ... DROP VALUE -- removing enum values
    # requires rebuilding the type (create new type, migrate columns,
    # drop old type). Not implemented since these values, once in use
    # by live Tournament/HomeCategoryBox rows, can't be safely dropped
    # without also handling those rows; treat this migration as
    # forward-only.
    pass