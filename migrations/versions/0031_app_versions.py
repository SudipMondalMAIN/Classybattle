"""add app_versions table for force/soft update feature

Revision ID: 0031_app_versions
Revises: 0030_txn_no
Create Date: 2026-08-07

Backs the Flutter splash-screen update check: one row per platform
(android/ios) holding the latest version, minimum supported version,
force_update flag, and the store URL/title/message to show.
"""
import uuid

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "0031_app_versions"
down_revision = "0030_txn_no"
branch_labels = None
depends_on = None

app_platform_enum = postgresql.ENUM("android", "ios", name="app_platform")


def upgrade() -> None:
    app_platform_enum.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "app_versions",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            default=uuid.uuid4,
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "platform",
            postgresql.ENUM("android", "ios", name="app_platform", create_type=False),
            nullable=False,
        ),
        sa.Column("latest_version", sa.String(length=20), nullable=False),
        sa.Column("latest_build_number", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("min_supported_version", sa.String(length=20), nullable=False),
        sa.Column("force_update", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("update_url", sa.String(length=500), nullable=False),
        sa.Column(
            "update_title",
            sa.String(length=150),
            nullable=False,
            server_default="Update Available",
        ),
        sa.Column(
            "update_message",
            sa.Text(),
            nullable=False,
            server_default="A new version of the app is available.",
        ),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.UniqueConstraint("platform", name="uq_app_versions_platform"),
    )
    op.create_index("ix_app_versions_platform", "app_versions", ["platform"])


def downgrade() -> None:
    op.drop_index("ix_app_versions_platform", table_name="app_versions")
    op.drop_table("app_versions")
    app_platform_enum.drop(op.get_bind(), checkfirst=True)
