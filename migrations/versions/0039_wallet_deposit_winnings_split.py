"""wallet deposit/winnings balance split

Revision ID: 0039_wallet_split
Revises: 0038_support_chat
Create Date: 2026-08-21

Splits Wallet.available_balance into two buckets:
- deposit_balance: UPI top-ups. Spendable on tournament entry only.
- winnings_balance: prize payouts/refunds/bonuses. Spendable on entry
  AND withdrawable.

Existing available_balance is migrated entirely into winnings_balance
(safe default: money already in the wallet stays fully usable,
including withdrawable, exactly as it already was before this split).
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0039_wallet_split"
down_revision: Union[str, None] = "0038_support_chat"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()

    wallet_balance_source = postgresql.ENUM(
        "deposit", "winnings", "mixed", name="wallet_balance_source", create_type=False
    )
    wallet_balance_source.create(bind, checkfirst=True)

    # ------------------------------------------------------------------
    # wallets: add deposit_balance / winnings_balance, migrate data,
    # drop available_balance (it is now a Python-level property).
    # ------------------------------------------------------------------
    op.add_column(
        "wallets",
        sa.Column("deposit_balance", sa.Numeric(14, 2), nullable=False, server_default="0"),
    )
    op.add_column(
        "wallets",
        sa.Column("winnings_balance", sa.Numeric(14, 2), nullable=False, server_default="0"),
    )
    op.execute("UPDATE wallets SET winnings_balance = available_balance")
    op.drop_constraint("ck_wallets_available_balance_non_negative", "wallets", type_="check")
    op.drop_column("wallets", "available_balance")
    op.create_check_constraint(
        "ck_wallets_deposit_balance_non_negative", "wallets", "deposit_balance >= 0"
    )
    op.create_check_constraint(
        "ck_wallets_winnings_balance_non_negative", "wallets", "winnings_balance >= 0"
    )

    # ------------------------------------------------------------------
    # wallet_transactions: add balance_source / deposit_delta /
    # winnings_delta / deposit_balance_after / winnings_balance_after.
    # ------------------------------------------------------------------
    op.add_column(
        "wallet_transactions",
        sa.Column(
            "balance_source",
            wallet_balance_source,
            nullable=False,
            server_default="winnings",
        ),
    )
    op.add_column(
        "wallet_transactions",
        sa.Column("deposit_delta", sa.Numeric(14, 2), nullable=False, server_default="0"),
    )
    op.add_column(
        "wallet_transactions",
        sa.Column("winnings_delta", sa.Numeric(14, 2), nullable=False, server_default="0"),
    )
    op.add_column(
        "wallet_transactions",
        sa.Column("deposit_balance_after", sa.Numeric(14, 2), nullable=True),
    )
    op.add_column(
        "wallet_transactions",
        sa.Column("winnings_balance_after", sa.Numeric(14, 2), nullable=True),
    )
    # Backfill: every historical row's balance was entirely "winnings" by
    # the same rule used above, and its full available_balance_after
    # snapshot maps onto winnings_balance_after (deposit stays 0).
    op.execute(
        "UPDATE wallet_transactions SET "
        "winnings_delta = CASE WHEN type IN ('credit','refund','bonus') THEN amount "
        "WHEN type IN ('debit','hold') THEN -amount ELSE 0 END, "
        "deposit_balance_after = 0, "
        "winnings_balance_after = available_balance_after"
    )
    op.alter_column("wallet_transactions", "deposit_balance_after", nullable=False)
    op.alter_column("wallet_transactions", "winnings_balance_after", nullable=False)


def downgrade() -> None:
    op.execute("UPDATE wallets SET winnings_balance = winnings_balance + deposit_balance")
    op.add_column(
        "wallets",
        sa.Column("available_balance", sa.Numeric(14, 2), nullable=False, server_default="0"),
    )
    op.execute("UPDATE wallets SET available_balance = winnings_balance")
    op.drop_constraint("ck_wallets_deposit_balance_non_negative", "wallets", type_="check")
    op.drop_constraint("ck_wallets_winnings_balance_non_negative", "wallets", type_="check")
    op.create_check_constraint(
        "ck_wallets_available_balance_non_negative", "wallets", "available_balance >= 0"
    )
    op.drop_column("wallets", "deposit_balance")
    op.drop_column("wallets", "winnings_balance")

    op.drop_column("wallet_transactions", "winnings_balance_after")
    op.drop_column("wallet_transactions", "deposit_balance_after")
    op.drop_column("wallet_transactions", "winnings_delta")
    op.drop_column("wallet_transactions", "deposit_delta")
    op.drop_column("wallet_transactions", "balance_source")

    bind = op.get_bind()
    postgresql.ENUM(name="wallet_balance_source").drop(bind, checkfirst=True)
