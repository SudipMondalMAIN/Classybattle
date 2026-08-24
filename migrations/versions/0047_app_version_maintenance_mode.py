"""app version maintenance mode -- kill-switch independent of version numbers

Revision ID: 0047_app_version_maintenance_mode
Revises: 0046_backfill_player_statistics
Create Date: 2026-08-24

Adds app_versions.maintenance_mode, a boolean the admin panel can flip to
force EVERY installed app (any version) onto the blocking update screen,
without having to fake latest_version/min_supported_version to trigger
force_update. Defaults to false so existing force/soft-update behavior is
unaffected until an admin explicitly turns maintenance on.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0047_app_version_maintenance_mode"
down_revision: Union[str, None] = "0046_backfill_player_statistics"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "app_versions",
        sa.Column(
            "maintenance_mode",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )


def downgrade() -> None:
    op.drop_column("app_versions", "maintenance_mode")
