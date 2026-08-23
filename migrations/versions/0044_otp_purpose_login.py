"""otp purpose login — adds LOGIN value for OTP-based login

Revision ID: 0044_otp_purpose_login
Revises: 0043_telegram_authorized_chats
Create Date: 2026-08-23

Adds "login" to the otp_purpose Postgres enum so OTPs can be issued
for logging in (in addition to the existing signup_verification and
password_reset purposes). Postgres enum values can only be added, not
removed, inside a transaction-safe way via ALTER TYPE ... ADD VALUE.
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0044_otp_purpose_login"
down_revision: Union[str, None] = "0043_telegram_authorized_chats"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ALTER TYPE ... ADD VALUE cannot run inside a transaction block in
    # older Postgres versions; alembic runs each migration in its own
    # transaction by default, so this is executed with autocommit.
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE otp_purpose ADD VALUE IF NOT EXISTS 'login'")


def downgrade() -> None:
    # Postgres does not support removing a value from an enum type.
    # Downgrading this migration is a no-op; the 'login' value simply
    # stays unused if rolled back.
    pass
