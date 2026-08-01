"""
Team Community System models — Phase 15B (Team Invitations, Join Requests,
Announcements & Activity Feed).

Follows the same patterns established by the Team System (Phase 6) and the
Social System (Phase 15A):

- TeamInvitation / TeamJoinRequest: one row per (team, user) pair with a
  status state machine (pending/accepted/rejected/cancelled/expired),
  mirroring `Friendship`'s "ledger of truth" pattern — a fresh
  invite/request reopens the existing row instead of creating duplicates.
- TeamAnnouncement: captain/organizer broadcast posts scoped to a team.
- TeamActivityFeedEntry: append-only feed row covering membership changes,
  invitations, join requests, announcements and team status changes. Also
  doubles as the source of truth for "Team Member History" and "Team Event
  History" (both are filtered views over this same table), avoiding a
  redesign of the existing Team/TeamMember schema.
"""
from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, Enum, ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import BaseModel
from app.database.types import PortableJSONB, str_enum


class TeamInvitationStatus(str, enum.Enum):
    PENDING = "pending"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    CANCELLED = "cancelled"
    EXPIRED = "expired"


class TeamJoinRequestStatus(str, enum.Enum):
    PENDING = "pending"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    CANCELLED = "cancelled"


class TeamActivityType(str, enum.Enum):
    MEMBER_JOINED = "member_joined"
    MEMBER_LEFT = "member_left"
    MEMBER_REMOVED = "member_removed"
    CAPTAIN_TRANSFERRED = "captain_transferred"
    INVITATION_SENT = "invitation_sent"
    INVITATION_ACCEPTED = "invitation_accepted"
    INVITATION_REJECTED = "invitation_rejected"
    INVITATION_CANCELLED = "invitation_cancelled"
    JOIN_REQUEST_SENT = "join_request_sent"
    JOIN_REQUEST_ACCEPTED = "join_request_accepted"
    JOIN_REQUEST_REJECTED = "join_request_rejected"
    JOIN_REQUEST_CANCELLED = "join_request_cancelled"
    ANNOUNCEMENT_POSTED = "announcement_posted"
    ANNOUNCEMENT_UPDATED = "announcement_updated"
    ANNOUNCEMENT_DELETED = "announcement_deleted"
    TEAM_LOCKED = "team_locked"
    TEAM_UNLOCKED = "team_unlocked"
    TEAM_DISBANDED = "team_disbanded"


# Categorization used to serve "Team Member History" as a filtered view
# over the same append-only feed table (no schema duplication).
MEMBER_HISTORY_ACTIVITY_TYPES: tuple[TeamActivityType, ...] = (
    TeamActivityType.MEMBER_JOINED,
    TeamActivityType.MEMBER_LEFT,
    TeamActivityType.MEMBER_REMOVED,
    TeamActivityType.CAPTAIN_TRANSFERRED,
)


class TeamInvitation(BaseModel):
    """One row per (team, invitee) pair. A cancelled/rejected/expired
    invitation can be reopened by a fresh invite rather than creating a
    duplicate row, mirroring `Friendship`."""

    __tablename__ = "team_invitations"
    __table_args__ = (
        UniqueConstraint("team_id", "invitee_id", name="uq_team_invitation_team_invitee"),
        Index("ix_team_invitations_team_status", "team_id", "status"),
        Index("ix_team_invitations_invitee_status", "invitee_id", "status"),
    )

    team_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("teams.id", ondelete="CASCADE"), nullable=False, index=True
    )
    tournament_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tournaments.id", ondelete="CASCADE"), nullable=False, index=True
    )
    inviter_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    invitee_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    status: Mapped[TeamInvitationStatus] = mapped_column(
        str_enum(TeamInvitationStatus, "team_invitation_status"),
        default=TeamInvitationStatus.PENDING,
        server_default=TeamInvitationStatus.PENDING.value,
        nullable=False,
        index=True,
    )
    message: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    responded_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    team: Mapped["Team"] = relationship(lazy="selectin")  # noqa: F821
    inviter: Mapped["User"] = relationship(foreign_keys=[inviter_id], lazy="selectin")  # noqa: F821
    invitee: Mapped["User"] = relationship(foreign_keys=[invitee_id], lazy="selectin")  # noqa: F821

    def __repr__(self) -> str:
        return f"<TeamInvitation id={self.id} team_id={self.team_id} invitee_id={self.invitee_id} status={self.status}>"


class TeamJoinRequest(BaseModel):
    """One row per (team, user) pair — a user asking to join a team,
    reviewed by the captain/organizer/admin."""

    __tablename__ = "team_join_requests"
    __table_args__ = (
        UniqueConstraint("team_id", "user_id", name="uq_team_join_request_team_user"),
        Index("ix_team_join_requests_team_status", "team_id", "status"),
        Index("ix_team_join_requests_user_status", "user_id", "status"),
    )

    team_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("teams.id", ondelete="CASCADE"), nullable=False, index=True
    )
    tournament_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tournaments.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    status: Mapped[TeamJoinRequestStatus] = mapped_column(
        str_enum(TeamJoinRequestStatus, "team_join_request_status"),
        default=TeamJoinRequestStatus.PENDING,
        server_default=TeamJoinRequestStatus.PENDING.value,
        nullable=False,
        index=True,
    )
    message: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    responded_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    reviewed_by_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    team: Mapped["Team"] = relationship(lazy="selectin")  # noqa: F821
    user: Mapped["User"] = relationship(foreign_keys=[user_id], lazy="selectin")  # noqa: F821

    def __repr__(self) -> str:
        return f"<TeamJoinRequest id={self.id} team_id={self.team_id} user_id={self.user_id} status={self.status}>"


class TeamAnnouncement(BaseModel):
    """Captain/organizer broadcast post scoped to a team."""

    __tablename__ = "team_announcements"
    __table_args__ = (
        Index("ix_team_announcements_team_created", "team_id", "created_at"),
        Index("ix_team_announcements_team_pinned", "team_id", "is_pinned"),
    )

    team_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("teams.id", ondelete="CASCADE"), nullable=False, index=True
    )
    author_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    content: Mapped[str] = mapped_column(String(2000), nullable=False)
    is_pinned: Mapped[bool] = mapped_column(default=False, server_default="false", nullable=False)

    team: Mapped["Team"] = relationship(lazy="selectin")  # noqa: F821
    author: Mapped[Optional["User"]] = relationship(lazy="selectin")  # noqa: F821

    def __repr__(self) -> str:
        return f"<TeamAnnouncement id={self.id} team_id={self.team_id} title={self.title!r}>"


class TeamActivityFeedEntry(BaseModel):
    """Append-only feed emitted for `team_id`; backs the Team Activity
    Feed, Team Member History and Team Event History read APIs — all are
    filtered views over this one table, keyed on `activity_type`."""

    __tablename__ = "team_activity_feed_entries"
    __table_args__ = (
        Index("ix_team_activity_feed_team_created", "team_id", "created_at"),
        Index("ix_team_activity_feed_team_type", "team_id", "activity_type"),
        UniqueConstraint("event_key", name="uq_team_activity_feed_event_key"),
    )

    team_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("teams.id", ondelete="CASCADE"), nullable=False, index=True
    )
    actor_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    activity_type: Mapped[TeamActivityType] = mapped_column(
        str_enum(TeamActivityType, "team_activity_type"), nullable=False, index=True
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    meta_data: Mapped[Optional[dict]] = mapped_column(PortableJSONB, nullable=True)
    # Idempotency key, e.g. "team_invite_accepted:<invitation_id>", so
    # automatic event hooks are safe to call more than once.
    event_key: Mapped[Optional[str]] = mapped_column(String(255), nullable=True, unique=True, index=True)

    team: Mapped["Team"] = relationship(lazy="selectin")  # noqa: F821
    actor: Mapped[Optional["User"]] = relationship(lazy="selectin")  # noqa: F821

    def __repr__(self) -> str:
        return f"<TeamActivityFeedEntry id={self.id} team_id={self.team_id} type={self.activity_type}>"
