"""add tournaments.starts_at for chronological (time-of-day) slot ordering

Revision ID: 0036_tournament_starts_at
Revises: 0035_custom_match_claims
Create Date: 2026-08-15

The tournament list was ordering by created_at (batch-generation order),
not by the slot's actual scheduled time -- so a 10:00 IST slot could show
below an 8:00 PM IST slot generated in the same/earlier batch. This adds
a real, sortable, absolute-time column and backfills it for existing
schedule-generated slots by parsing the deterministic
`<template_slug>-<YYYY-MM-DD>-<HHMM>` slug suffix that
SlotGeneratorService already stamps every generated slot with (those
HHMM values are IST wall-clock, per that service).
"""
import re
from datetime import datetime, timedelta, timezone

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "0036_tournament_starts_at"
down_revision = "0035_custom_match_claims"
branch_labels = None
depends_on = None

IST = timezone(timedelta(hours=5, minutes=30))
_SLUG_RE = re.compile(r"-(\d{4}-\d{2}-\d{2})-(\d{2})(\d{2})$")


def upgrade() -> None:
    op.add_column(
        "tournaments",
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_tournaments_starts_at", "tournaments", ["starts_at"], unique=False
    )

    bind = op.get_bind()
    rows = bind.execute(
        sa.text(
            "SELECT id, slug FROM tournaments "
            "WHERE is_recurring_schedule IS NOT TRUE"
        )
    ).fetchall()

    for row in rows:
        m = _SLUG_RE.search(row.slug)
        if not m:
            continue
        date_str, hour_str, minute_str = m.groups()
        try:
            naive = datetime.strptime(
                f"{date_str} {hour_str}:{minute_str}", "%Y-%m-%d %H:%M"
            )
        except ValueError:
            continue
        starts_at_utc = naive.replace(tzinfo=IST).astimezone(timezone.utc)
        bind.execute(
            sa.text("UPDATE tournaments SET starts_at = :starts_at WHERE id = :id"),
            {"starts_at": starts_at_utc, "id": row.id},
        )


def downgrade() -> None:
    op.drop_index("ix_tournaments_starts_at", table_name="tournaments")
    op.drop_column("tournaments", "starts_at")
