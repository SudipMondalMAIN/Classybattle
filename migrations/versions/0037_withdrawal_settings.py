"""withdrawal min/max amount settings

Revision ID: 0037_withdrawal_settings
Revises: 0036_tournament_starts_at
Create Date: 2026-08-15

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0037_withdrawal_settings"
down_revision: Union[str, None] = "0036_tournament_starts_at"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "payment_settings",
        sa.Column("min_withdrawal_amount", sa.Numeric(14, 2), server_default="100", nullable=False),
    )
    op.add_column(
        "payment_settings",
        sa.Column("max_withdrawal_amount", sa.Numeric(14, 2), server_default="100000", nullable=False),
    )


def downgrade() -> None:
    op.drop_column("payment_settings", "max_withdrawal_amount")
    op.drop_column("payment_settings", "min_withdrawal_amount")
