"""add short_id (human-friendly 8-digit id) to key tables

Revision ID: 0023_short_ids
Revises: 0022_room_notif_event
Create Date: 2026-08-02

Adds a `short_id` BIGINT column (backed by its own per-table sequence,
starting at 10,000,001) to the tables admins actually search/reference
day-to-day: users, tournaments, teams, matches, participants,
payment_requests, withdrawal_requests, reports, moderation_actions.

The UUID `id` column remains the real primary/foreign key everywhere —
`short_id` is purely a human-friendly, easy-to-type/search alternate key
for the admin panel. Existing rows are backfilled in id order so older
records get lower numbers.
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0023_short_ids"
down_revision: Union[str, None] = "0022_room_notif_event"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLES = [
    "users",
    "tournaments",
    "teams",
    "matches",
    "participants",
    "payment_requests",
    "withdrawal_requests",
    "reports",
    "moderation_actions",
]


def upgrade() -> None:
    bind = op.get_bind()
    for table in TABLES:
        seq_name = f"{table}_short_id_seq"

        op.execute(f"CREATE SEQUENCE IF NOT EXISTS {seq_name} START WITH 10000001 INCREMENT BY 1")
        op.execute(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS short_id BIGINT")

        # Backfill any existing rows in creation order so older records
        # get lower short_ids.
        op.execute(
            f"""
            UPDATE {table}
            SET short_id = nextval('{seq_name}')
            WHERE short_id IS NULL
            """
        )

        op.execute(f"ALTER TABLE {table} ALTER COLUMN short_id SET DEFAULT nextval('{seq_name}')")
        op.execute(f"ALTER TABLE {table} ALTER COLUMN short_id SET NOT NULL")
        op.execute(
            f"ALTER TABLE {table} ADD CONSTRAINT uq_{table}_short_id UNIQUE (short_id)"
        )
        op.execute(f"CREATE INDEX IF NOT EXISTS ix_{table}_short_id ON {table} (short_id)")
        op.execute(f"ALTER SEQUENCE {seq_name} OWNED BY {table}.short_id")


def downgrade() -> None:
    for table in TABLES:
        seq_name = f"{table}_short_id_seq"
        op.execute(f"DROP INDEX IF EXISTS ix_{table}_short_id")
        op.execute(f"ALTER TABLE {table} DROP CONSTRAINT IF EXISTS uq_{table}_short_id")
        op.execute(f"ALTER TABLE {table} DROP COLUMN IF EXISTS short_id")
        op.execute(f"DROP SEQUENCE IF EXISTS {seq_name}")
