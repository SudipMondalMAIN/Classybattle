"""initial schema - phase 1 foundation and auth

Revision ID: 0001_initial
Revises:
Create Date: 2026-07-30

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001_initial"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _base_columns():
    return [
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False, unique=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    ]


def upgrade() -> None:
    user_role = postgresql.ENUM("user", "admin", "super_admin", name="user_role", create_type=False)
    user_status = postgresql.ENUM("active", "suspended", "banned", name="user_status", create_type=False)
    otp_purpose = postgresql.ENUM("signup_verification", "password_reset", name="otp_purpose", create_type=False)
    notif_channel = postgresql.ENUM("push", "email", "in_app", name="notification_channel", create_type=False)
    notif_status = postgresql.ENUM("pending", "sent", "failed", name="notification_status", create_type=False)

    bind = op.get_bind()
    user_role.create(bind, checkfirst=True)
    user_status.create(bind, checkfirst=True)
    otp_purpose.create(bind, checkfirst=True)
    notif_channel.create(bind, checkfirst=True)
    notif_status.create(bind, checkfirst=True)

    # ---------------- users ----------------
    op.create_table(
        "users",
        *_base_columns(),
        sa.Column("full_name", sa.String(150), nullable=False),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("phone_number", sa.String(20), nullable=False),
        sa.Column("hashed_password", sa.String(255), nullable=False),
        sa.Column("role", user_role, nullable=False, server_default="user"),
        sa.Column("status", user_status, nullable=False, server_default="active"),
        sa.Column("is_email_verified", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("country", sa.String(100), nullable=True),
        sa.Column("avatar_id", sa.String(50), nullable=True),
        sa.Column("bio", sa.String(500), nullable=True),
        sa.UniqueConstraint("email", name="uq_users_email"),
        sa.UniqueConstraint("phone_number", name="uq_users_phone_number"),
    )
    op.create_index("ix_users_email", "users", ["email"])
    op.create_index("ix_users_phone_number", "users", ["phone_number"])

    # ---------------- otps ----------------
    op.create_table(
        "otps",
        *_base_columns(),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("otp_hash", sa.String(255), nullable=False),
        sa.Column("purpose", otp_purpose, nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("attempts", sa.Integer, nullable=False, server_default="0"),
        sa.Column("is_used", sa.Boolean, nullable=False, server_default=sa.false()),
    )
    op.create_index("ix_otps_email", "otps", ["email"])

    # ---------------- refresh_tokens ----------------
    op.create_table(
        "refresh_tokens",
        *_base_columns(),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("token", sa.String(500), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("is_revoked", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("device_info", sa.String(255), nullable=True),
        sa.UniqueConstraint("token", name="uq_refresh_tokens_token"),
    )
    op.create_index("ix_refresh_tokens_user_id", "refresh_tokens", ["user_id"])
    op.create_index("ix_refresh_tokens_token", "refresh_tokens", ["token"])

    # ---------------- games ----------------
    op.create_table(
        "games",
        *_base_columns(),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("slug", sa.String(100), nullable=False),
        sa.Column("icon_url", sa.String(500), nullable=True),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("profile_schema", postgresql.JSONB, nullable=False, server_default="[]"),
        sa.UniqueConstraint("name", name="uq_games_name"),
        sa.UniqueConstraint("slug", name="uq_games_slug"),
    )
    op.create_index("ix_games_name", "games", ["name"])
    op.create_index("ix_games_slug", "games", ["slug"])

    # ---------------- user_game_profiles ----------------
    op.create_table(
        "user_game_profiles",
        *_base_columns(),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("game_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("games.id", ondelete="CASCADE"), nullable=False),
        sa.Column("data", postgresql.JSONB, nullable=False, server_default="{}"),
        sa.UniqueConstraint("user_id", "game_id", name="uq_user_game_profile"),
    )
    op.create_index("ix_user_game_profiles_user_id", "user_game_profiles", ["user_id"])
    op.create_index("ix_user_game_profiles_game_id", "user_game_profiles", ["game_id"])

    # ---------------- notifications ----------------
    op.create_table(
        "notifications",
        *_base_columns(),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("body", sa.String(1000), nullable=False),
        sa.Column("channel", notif_channel, nullable=False),
        sa.Column("status", notif_status, nullable=False, server_default="pending"),
        sa.Column("is_read", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("meta_data", postgresql.JSONB, nullable=True),
    )
    op.create_index("ix_notifications_user_id", "notifications", ["user_id"])

    # ---------------- device_tokens ----------------
    op.create_table(
        "device_tokens",
        *_base_columns(),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("fcm_token", sa.String(500), nullable=False),
        sa.Column("platform", sa.String(20), nullable=False, server_default="android"),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.UniqueConstraint("user_id", "fcm_token", name="uq_user_fcm_token"),
    )
    op.create_index("ix_device_tokens_user_id", "device_tokens", ["user_id"])


def downgrade() -> None:
    op.drop_table("device_tokens")
    op.drop_table("notifications")
    op.drop_table("user_game_profiles")
    op.drop_table("games")
    op.drop_table("refresh_tokens")
    op.drop_table("otps")
    op.drop_table("users")

    bind = op.get_bind()
    postgresql.ENUM(name="notification_status").drop(bind, checkfirst=True)
    postgresql.ENUM(name="notification_channel").drop(bind, checkfirst=True)
    postgresql.ENUM(name="otp_purpose").drop(bind, checkfirst=True)
    postgresql.ENUM(name="user_status").drop(bind, checkfirst=True)
    postgresql.ENUM(name="user_role").drop(bind, checkfirst=True)