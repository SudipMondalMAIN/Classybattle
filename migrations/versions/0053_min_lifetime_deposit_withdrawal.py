"""minimum lifetime deposit required before withdrawal is allowed

Revision ID: 0053_min_lifetime_deposit_withdrawal
Revises: 0052_schedule_slot_running_number
Create Date: 2026-09-09

Adds `min_lifetime_deposit_for_withdrawal` to payment_settings. A user
becomes eligible to withdraw only once the SUM of their approved
deposits (lifetime, regardless of how many separate deposits) reaches
this amount. Default ₹20, admin-configurable.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0053_min_lifetime_deposit_withdrawal"
down_revision: Union[str, None] = "0052_schedule_slot_running_number"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "payment_settings",
        sa.Column(
            "min_lifetime_deposit_for_withdrawal",
            sa.Numeric(14, 2),
            server_default="20",
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("payment_settings", "min_lifetime_deposit_for_withdrawal")
