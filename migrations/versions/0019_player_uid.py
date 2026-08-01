"""add player_uid to users

Revision ID: 0019_player_uid
Revises: 0018_payments
Create Date: 2026-08-01

"""
import secrets
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0019_player_uid"
down_revision: Union[str, None] = "0018_payments"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_NUM_DIGITS = 8


def _generate_uid() -> str:
    return str(secrets.randbelow(10**_NUM_DIGITS)).zfill(_NUM_DIGITS)


def upgrade() -> None:
    bind = op.get_bind()

    # 1. Add as nullable first so existing rows aren't rejected.
    op.add_column("users", sa.Column("player_uid", sa.String(length=8), nullable=True))

    # 2. Backfill every existing user with a unique 8-digit UID.
    result = bind.execute(sa.text("SELECT id FROM users"))
    existing_uids: set[str] = set()
    for (user_id,) in result:
        uid = _generate_uid()
        while uid in existing_uids:
            uid = _generate_uid()
        existing_uids.add(uid)
        bind.execute(
            sa.text("UPDATE users SET player_uid = :uid WHERE id = :id"),
            {"uid": uid, "id": user_id},
        )

    # 3. Now that every row has a value, enforce NOT NULL + uniqueness.
    op.alter_column("users", "player_uid", nullable=False)
    op.create_index("ix_users_player_uid", "users", ["player_uid"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_users_player_uid", table_name="users")
    op.drop_column("users", "player_uid")
