"""
Social System models — Phase 15A (Player Profiles & Social System).

- PlayerProfile: 1:1 extension of User with social/presence fields.
- Friendship: single row per unordered pair (requester/addressee) with a
  status state machine (pending/accepted/rejected/cancelled/blocked),
  mirroring the Wallet/AuditLog "ledger of truth" pattern used elsewhere.
- Follow: one-directional follow edge (follower -> followee).
- ActivityFeedEntry: append-only feed row generated from other modules'
  events (match/tournament/wallet/prize/friend), fanned out to the
  actor's friends/followers at read time.
"""
from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import BaseModel
from app.database.types import PortableJSONB


class ProfileVisibility(str, enum.Enum):
    PUBLIC = "public"
    PRIVATE = "private"
    FRIENDS_ONLY = "friends_only"


class FriendshipStatus(str, enum.Enum):
    PENDING = "pending"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    CANCELLED = "cancelled"
    BLOCKED = "blocked"


class ActivityType(str, enum.Enum):
    FRIEND_ADDED = "friend_added"
    TOURNAMENT_JOINED = "tournament_joined"
    TOURNAMENT_WON = "tournament_won"
    MATCH_PLAYED = "match_played"
    MATCH_WON = "match_won"
    WALLET_CREDITED = "wallet_credited"
    PRIZE_WON = "prize_won"


class PlayerProfile(BaseModel):
    """Public/private social profile layered on top of `User`."""

    __tablename__ = "player_profiles"
    __table_args__ = (UniqueConstraint("user_id", name="uq_player_profiles_user_id"),)

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )

    display_name: Mapped[Optional[str]] = mapped_column(String(150), nullable=True)
    bio: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    avatar_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    cover_image_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)

    visibility: Mapped[ProfileVisibility] = mapped_column(
        Enum(ProfileVisibility, name="profile_visibility"),
        default=ProfileVisibility.PUBLIC,
        server_default=ProfileVisibility.PUBLIC.value,
        nullable=False,
    )
    show_match_history: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true", nullable=False)
    show_stats: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true", nullable=False)

    social_links: Mapped[Optional[dict]] = mapped_column(PortableJSONB, nullable=True)

    is_online: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false", nullable=False)
    last_seen_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    friends_count: Mapped[int] = mapped_column(default=0, server_default="0", nullable=False)
    followers_count: Mapped[int] = mapped_column(default=0, server_default="0", nullable=False)
    following_count: Mapped[int] = mapped_column(default=0, server_default="0", nullable=False)

    user: Mapped["User"] = relationship(lazy="selectin")  # noqa: F821

    def __repr__(self) -> str:
        return f"<PlayerProfile user_id={self.user_id}>"


class Friendship(BaseModel):
    """One row per requester/addressee pair. `requester_id` is always the
    user who sent the original request, regardless of current status."""

    __tablename__ = "friendships"
    __table_args__ = (
        UniqueConstraint("requester_id", "addressee_id", name="uq_friendship_pair"),
        Index("ix_friendship_addressee_status", "addressee_id", "status"),
        Index("ix_friendship_requester_status", "requester_id", "status"),
    )

    requester_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    addressee_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    status: Mapped[FriendshipStatus] = mapped_column(
        Enum(FriendshipStatus, name="friendship_status"),
        default=FriendshipStatus.PENDING,
        server_default=FriendshipStatus.PENDING.value,
        nullable=False,
        index=True,
    )
    # Who most recently changed the status (used to know who blocked whom).
    action_by_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    responded_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    def __repr__(self) -> str:
        return f"<Friendship {self.requester_id}->{self.addressee_id} status={self.status}>"


class Follow(BaseModel):
    """One-directional follow edge: follower_id follows followee_id."""

    __tablename__ = "follows"
    __table_args__ = (
        UniqueConstraint("follower_id", "followee_id", name="uq_follow_pair"),
        Index("ix_follow_followee", "followee_id"),
        Index("ix_follow_follower", "follower_id"),
    )

    follower_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    followee_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )

    def __repr__(self) -> str:
        return f"<Follow {self.follower_id}->{self.followee_id}>"


class ActivityFeedEntry(BaseModel):
    """Append-only activity emitted by `actor_id`; readers see entries
    from users they follow/are friends with plus their own."""

    __tablename__ = "activity_feed_entries"
    __table_args__ = (
        Index("ix_activity_feed_actor_created", "actor_id", "created_at"),
        UniqueConstraint("event_key", name="uq_activity_feed_event_key"),
    )

    actor_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    activity_type: Mapped[ActivityType] = mapped_column(
        Enum(ActivityType, name="activity_type"), nullable=False, index=True
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    meta_data: Mapped[Optional[dict]] = mapped_column(PortableJSONB, nullable=True)
    # Idempotency key, e.g. "match_played:<match_id>:<user_id>", so
    # automatic event hooks are safe to call more than once.
    event_key: Mapped[Optional[str]] = mapped_column(String(255), nullable=True, unique=True, index=True)

    def __repr__(self) -> str:
        return f"<ActivityFeedEntry actor_id={self.actor_id} type={self.activity_type}>"
