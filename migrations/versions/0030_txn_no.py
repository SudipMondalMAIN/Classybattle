"""add 10-digit txn_no to payment_requests and withdrawal_requests

Revision ID: 0030_txn_no
Revises: 0029_tournament_match_merge
Create Date: 2026-08-06

Adds a user-facing 10-digit numeric transaction number (`txn_no`) to
both deposit (payment_requests) and withdrawal (withdrawal_requests)
rows, distinct from the internal UUID `id` and the admin-facing
`short_id`. Added nullable first, backfilled for any existing rows,
then locked to NOT NULL + UNIQUE.
"""
import secrets

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "0030_txn_no"
down_revision = "0029_tournament_match_merge"
branch_labels = None
depends_on = None

_DIGITS = "0123456789"
_NONZERO_DIGITS = "123456789"


def _random_txn_no() -> str:
    return secrets.choice(_NONZERO_DIGITS) + "".join(
        secrets.choice(_DIGITS) for _ in range(9)
    )


def _backfill(table: str) -> None:
    conn = op.get_bind()
    rows = conn.execute(sa.text(f"SELECT id FROM {table}")).fetchall()
    seen = set()
    for (row_id,) in rows:
        txn_no = _random_txn_no()
        while txn_no in seen:
            txn_no = _random_txn_no()
        seen.add(txn_no)
        conn.execute(
            sa.text(f"UPDATE {table} SET txn_no = :txn_no WHERE id = :id"),
            {"txn_no": txn_no, "id": row_id},
        )


def upgrade() -> None:
    op.add_column(
        "payment_requests", sa.Column("txn_no", sa.String(length=10), nullable=True)
    )
    op.add_column(
        "withdrawal_requests", sa.Column("txn_no", sa.String(length=10), nullable=True)
    )

    _backfill("payment_requests")
    _backfill("withdrawal_requests")

    op.alter_column("payment_requests", "txn_no", nullable=False)
    op.alter_column("withdrawal_requests", "txn_no", nullable=False)

    op.create_index(
        "ix_payment_requests_txn_no", "payment_requests", ["txn_no"], unique=False
    )
    op.create_unique_constraint(
        "uq_payment_requests_txn_no", "payment_requests", ["txn_no"]
    )

    op.create_index(
        "ix_withdrawal_requests_txn_no", "withdrawal_requests", ["txn_no"], unique=False
    )
    op.create_unique_constraint(
        "uq_withdrawal_requests_txn_no", "withdrawal_requests", ["txn_no"]
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_withdrawal_requests_txn_no", "withdrawal_requests", type_="unique"
    )
    op.drop_index("ix_withdrawal_requests_txn_no", table_name="withdrawal_requests")
    op.drop_column("withdrawal_requests", "txn_no")

    op.drop_constraint("uq_payment_requests_txn_no", "payment_requests", type_="unique")
    op.drop_index("ix_payment_requests_txn_no", table_name="payment_requests")
    op.drop_column("payment_requests", "txn_no")
