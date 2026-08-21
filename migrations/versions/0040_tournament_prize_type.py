"""tournament prize type (rank / per_kill / win)

Revision ID: 0040_prize_type
Revises: 0039_wallet_split
Create Date: 2026-08-21

Adds admin-configurable prize-type selection to Tournament (schedules +
generated slots inherit this from their template, same pattern as
entry_fee/prize_pool):

- prize_type: rank | per_kill | win (default 'rank', backward compatible
  with every existing tournament which already behaves rank-based today).
- rank_prize_rules: JSONB list of {"rank": int, "amount": number} -- used
  when prize_type='rank'.
- per_kill_amount: ₹ paid per confirmed kill -- used when
  prize_type='per_kill'.
- win_amount: flat ₹ paid to the declared winner -- used when
  prize_type='win'.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0040_prize_type"
down_revision: Union[str, None] = "0039_wallet_split"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    prize_type_enum = postgresql.ENUM(
        "rank", "per_kill", "win", name="prize_type"
    )
    prize_type_enum.create(op.get_bind(), checkfirst=True)

    op.add_column(
        "tournaments",
        sa.Column(
            "prize_type",
            prize_type_enum,
            nullable=False,
            server_default="rank",
        ),
    )
    op.add_column(
        "tournaments",
        sa.Column("rank_prize_rules", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.add_column(
        "tournaments",
        sa.Column("per_kill_amount", sa.Numeric(10, 2), nullable=True),
    )
    op.add_column(
        "tournaments",
        sa.Column("win_amount", sa.Numeric(10, 2), nullable=True),
    )
    op.create_check_constraint(
        "ck_tournaments_per_kill_amount_non_negative",
        "tournaments",
        "per_kill_amount IS NULL OR per_kill_amount >= 0",
    )
    op.create_check_constraint(
        "ck_tournaments_win_amount_non_negative",
        "tournaments",
        "win_amount IS NULL OR win_amount >= 0",
    )


def downgrade() -> None:
    op.drop_constraint("ck_tournaments_win_amount_non_negative", "tournaments", type_="check")
    op.drop_constraint("ck_tournaments_per_kill_amount_non_negative", "tournaments", type_="check")
    op.drop_column("tournaments", "win_amount")
    op.drop_column("tournaments", "per_kill_amount")
    op.drop_column("tournaments", "rank_prize_rules")
    op.drop_column("tournaments", "prize_type")

    bind = op.get_bind()
    postgresql.ENUM(name="prize_type").drop(bind, checkfirst=True)
