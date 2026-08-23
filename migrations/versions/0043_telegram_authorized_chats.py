"""telegram authorized chats — admin bot

Revision ID: 0043_telegram_authorized_chats
Revises: 0042_schedule_category_duo
Create Date: 2026-08-23

Backs the new Telegram admin bot: one row per chat that has
authorized itself via /start <code>. Authorized chats receive
deposit/withdrawal notifications and can Confirm/Decline deposits.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0043_telegram_authorized_chats"
down_revision: Union[str, None] = "0042_schedule_category_duo"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "telegram_authorized_chats",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, unique=True, nullable=False),
        sa.Column("chat_id", sa.BigInteger(), nullable=False),
        sa.Column("chat_title", sa.String(length=255), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("authorized_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index(
        "ix_telegram_authorized_chats_chat_id",
        "telegram_authorized_chats",
        ["chat_id"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("ix_telegram_authorized_chats_chat_id", table_name="telegram_authorized_chats")
    op.drop_table("telegram_authorized_chats")
