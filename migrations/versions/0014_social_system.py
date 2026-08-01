"""player profiles & social system - phase 15a

Revision ID: 0014_social_system
Revises: 0013_notifications
Create Date: 2026-08-01

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0014_social_system"
down_revision: Union[str, None] = "0013_notifications"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    profile_visibility = postgresql.ENUM(
        "public", "private", "friends_only", name="profile_visibility", create_type=False
    )
    profile_visibility.create(op.get_bind(), checkfirst=True)

    friendship_status = postgresql.ENUM(
        "pending", "accepted", "rejected", "cancelled", "blocked", name="friendship_status", create_type=False
    )
    friendship_status.create(op.get_bind(), checkfirst=True)

    activity_type = postgresql.ENUM(
        "friend_added",
        "tournament_joined",
        "tournament_won",
        "match_played",
        "match_won",
        "wallet_credited",
        "prize_won",
        name="activity_type",
        create_type=False,
    )
    activity_type.create(op.get_bind(), checkfirst=True)

    # ------------------------------------------------------------------
    # player_profiles
    # ------------------------------------------------------------------
    op.create_table(
        "player_profiles",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False, unique=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("display_name", sa.String(length=150), nullable=True),
        sa.Column("bio", sa.String(length=500), nullable=True),
        sa.Column("avatar_url", sa.String(length=500), nullable=True),
        sa.Column("cover_image_url", sa.String(length=500), nullable=True),
        sa.Column("visibility", profile_visibility, nullable=False, server_default="public"),
        sa.Column("show_match_history", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("show_stats", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("social_links", postgresql.JSONB, nullable=True),
        sa.Column("is_online", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("friends_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("followers_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("following_count", sa.Integer, nullable=False, server_default="0"),
        sa.UniqueConstraint("user_id", name="uq_player_profiles_user_id"),
    )
    op.create_index("ix_player_profiles_user_id", "player_profiles", ["user_id"])

    # ------------------------------------------------------------------
    # friendships
    # ------------------------------------------------------------------
    op.create_table(
        "friendships",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False, unique=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "requester_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "addressee_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("status", friendship_status, nullable=False, server_default="pending"),
        sa.Column(
            "action_by_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("responded_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("requester_id", "addressee_id", name="uq_friendship_pair"),
    )
    op.create_index("ix_friendship_requester_id", "friendships", ["requester_id"])
    op.create_index("ix_friendship_addressee_id", "friendships", ["addressee_id"])
    op.create_index("ix_friendship_status", "friendships", ["status"])
    op.create_index("ix_friendship_addressee_status", "friendships", ["addressee_id", "status"])
    op.create_index("ix_friendship_requester_status", "friendships", ["requester_id", "status"])

    # ------------------------------------------------------------------
    # follows
    # ------------------------------------------------------------------
    op.create_table(
        "follows",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False, unique=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "follower_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "followee_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.UniqueConstraint("follower_id", "followee_id", name="uq_follow_pair"),
    )
    op.create_index("ix_follow_follower", "follows", ["follower_id"])
    op.create_index("ix_follow_followee", "follows", ["followee_id"])

    # ------------------------------------------------------------------
    # activity_feed_entries
    # ------------------------------------------------------------------
    op.create_table(
        "activity_feed_entries",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False, unique=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "actor_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("activity_type", activity_type, nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("meta_data", postgresql.JSONB, nullable=True),
        sa.Column("event_key", sa.String(length=255), nullable=True),
        sa.UniqueConstraint("event_key", name="uq_activity_feed_event_key"),
    )
    op.create_index("ix_activity_feed_actor_id", "activity_feed_entries", ["actor_id"])
    op.create_index("ix_activity_feed_activity_type", "activity_feed_entries", ["activity_type"])
    op.create_index("ix_activity_feed_event_key", "activity_feed_entries", ["event_key"])
    op.create_index(
        "ix_activity_feed_actor_created", "activity_feed_entries", ["actor_id", "created_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_activity_feed_actor_created", table_name="activity_feed_entries")
    op.drop_index("ix_activity_feed_event_key", table_name="activity_feed_entries")
    op.drop_index("ix_activity_feed_activity_type", table_name="activity_feed_entries")
    op.drop_index("ix_activity_feed_actor_id", table_name="activity_feed_entries")
    op.drop_table("activity_feed_entries")

    op.drop_index("ix_follow_followee", table_name="follows")
    op.drop_index("ix_follow_follower", table_name="follows")
    op.drop_table("follows")

    op.drop_index("ix_friendship_requester_status", table_name="friendships")
    op.drop_index("ix_friendship_addressee_status", table_name="friendships")
    op.drop_index("ix_friendship_status", table_name="friendships")
    op.drop_index("ix_friendship_addressee_id", table_name="friendships")
    op.drop_index("ix_friendship_requester_id", table_name="friendships")
    op.drop_table("friendships")

    op.drop_index("ix_player_profiles_user_id", table_name="player_profiles")
    op.drop_table("player_profiles")

    bind = op.get_bind()
    postgresql.ENUM(name="activity_type").drop(bind, checkfirst=True)
    postgresql.ENUM(name="friendship_status").drop(bind, checkfirst=True)
    postgresql.ENUM(name="profile_visibility").drop(bind, checkfirst=True)
