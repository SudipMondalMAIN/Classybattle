"""add room_details_published notification event type

Revision ID: 0022_room_notif_event
Revises: 0021_withdrawals
Create Date: 2026-08-02

"""
from typing import Sequence, Union

from alembic import op

revision: str = "0022_room_notif_event"
down_revision: Union[str, None] = "0021_withdrawals"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ALTER TYPE ... ADD VALUE cannot run inside a transaction block in
    # older PG drivers; psycopg/asyncpg + alembic run each migration in
    # its own transaction by default which Postgres 12+ supports fine for
    # ADD VALUE, so this is safe as-is.
    op.execute("ALTER TYPE notification_event_type ADD VALUE IF NOT EXISTS 'room_details_published'")


def downgrade() -> None:
    # Postgres does not support removing a single enum value; a downgrade
    # would require recreating the type. Left as a no-op intentionally.
    pass