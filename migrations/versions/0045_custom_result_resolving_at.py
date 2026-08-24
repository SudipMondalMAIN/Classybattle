"""custom result resolving at -- CAS gate for 1v1 custom-tournament resolution

Revision ID: 0045_custom_result_resolving_at
Revises: 0044_otp_purpose_login
Create Date: 2026-08-23

Adds tournaments.custom_result_resolving_at, a nullable timestamp used
as a compare-and-swap gate for CustomMatchClaimService's auto-resolve
flow. See the accompanying service change: SELECT ... FOR UPDATE row
locks and pg_advisory_lock both failed to reliably serialize two
near-simultaneous "I Lost" submissions in production (confirmed via
wallet_transactions showing both players paid for the same 1v1). A
single conditional UPDATE ("... WHERE custom_result_resolving_at IS
NULL RETURNING id") is atomic at the row/MVCC level regardless of how
the DB pooler multiplexes connections, so it does not depend on lock
or session continuity the way the previous approaches did.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0045_custom_result_resolving_at"
down_revision: Union[str, None] = "0044_otp_purpose_login"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "tournaments",
        sa.Column("custom_result_resolving_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("tournaments", "custom_result_resolving_at")
