"""backfill missing player_statistics rows for existing users

Revision ID: 0046_backfill_player_statistics
Revises: 0045_custom_result_resolving_at
Create Date: 2026-08-24

Before this fix, a player_statistics row was only ever created the
first time a user's match/payout event ran through
LeaderboardService.record_match_completion /
record_admin_winner_payout. Users who signed up but never had such an
event recorded (e.g. never played, or only played before Phase 14
shipped) have no player_statistics row at all, so
PlayerStatisticsRepository.top() -- a plain SELECT over
player_statistics -- never returns them and they're invisible on the
leaderboard even though their account exists.

AuthService.verify_signup_otp now creates a zero-score row for every
*new* signup going forward. This migration does the equivalent,
one-time, for every user created before that change.
"""
import uuid
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0046_backfill_player_statistics"
down_revision: Union[str, None] = "0045_custom_result_resolving_at"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()

    # user ids that don't have a player_statistics row yet
    missing = conn.execute(
        sa.text(
            """
            SELECT u.id
            FROM users u
            LEFT JOIN player_statistics ps ON ps.user_id = u.id
            WHERE ps.id IS NULL
            """
        )
    ).fetchall()

    if not missing:
        return

    conn.execute(
        sa.text(
            """
            INSERT INTO player_statistics (id, user_id, created_at, updated_at)
            VALUES (:id, :user_id, now(), now())
            """
        ),
        [{"id": str(uuid.uuid4()), "user_id": row[0]} for row in missing],
    )


def downgrade() -> None:
    # Not reversible in a targeted way -- rows backfilled here are
    # indistinguishable from ones created normally afterwards.
    pass