"""otps: hold pending signup payload until OTP verification

Revision ID: 0028_otp_signup_payload
Revises: 0027_match_admin_results
Create Date: 2026-08-04

Signup no longer writes to `users` until the email OTP is verified.
The submitted signup details (full name, phone number, hashed password)
are now held on the OTP row itself so the account can be created only
once verification succeeds.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "0028_otp_signup_payload"
down_revision = "0027_match_admin_results"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "otps",
        sa.Column(
            "signup_payload",
            postgresql.JSONB().with_variant(sa.JSON(), "sqlite"),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("otps", "signup_payload")