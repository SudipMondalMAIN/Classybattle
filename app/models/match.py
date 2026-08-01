"""
Match model — Room Management & Match Lifecycle (Phase 7).
"""
import enum
import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import BaseModel
from app.database.types import str_enum


class MatchStatus(str, enum.Enum):
    DRAFT = "draft"
    SCHEDULED = "scheduled"
    ROOM_PUBLISHED = "room_published"
    CHECK_IN_OPEN = "check_in_open"
    READY = "ready"
    LIVE = "live"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class RoomStatus(str, enum.Enum):
    NOT_CREATED = "not_created"
    HIDDEN = "hidden"
    PUBLISHED = "published"
    EDITED = "edited"
    CLOSED = "closed"


# Explicit allowed forward transitions, mirroring the pattern used for
# TOURNAMENT_STATUS_TRANSITIONS / TEAM_STATUS_TRANSITIONS.
MATCH_STATUS_TRANSITIONS: dict[MatchStatus, set[MatchStatus]] = {
    MatchStatus.DRAFT: {MatchStatus.SCHEDULED, MatchStatus.CANCELLED},
    MatchStatus.SCHEDULED: {
        MatchStatus.ROOM_PUBLISHED,
        MatchStatus.SCHEDULED,
        MatchStatus.CANCELLED,
    },
    MatchStatus.ROOM_PUBLISHED: {
        MatchStatus.CHECK_IN_OPEN,
        MatchStatus.SCHEDULED,
        MatchStatus.CANCELLED,
    },
    MatchStatus.CHECK_IN_OPEN: {
        MatchStatus.READY,
        MatchStatus.CANCELLED,
    },
    MatchStatus.READY: {
        MatchStatus.LIVE,
        MatchStatus.CHECK_IN_OPEN,
        MatchStatus.CANCELLED,
    },
    MatchStatus.LIVE: {MatchStatus.COMPLETED, MatchStatus.CANCELLED},
    MatchStatus.COMPLETED: set(),
    MatchStatus.CANCELLED: set(),
}


class Match(BaseModel):
    __tablename__ = "matches"
    __table_args__ = (
        UniqueConstraint(
            "tournament_id",
            "round_number",
            "match_number",
            name="uq_matches_tournament_round_match_number",
        ),
        CheckConstraint("round_number > 0", name="ck_matches_round_number_positive"),
        CheckConstraint("match_number > 0", name="ck_matches_match_number_positive"),
        CheckConstraint(
            "scheduled_end IS NULL OR scheduled_start IS NULL OR scheduled_end > scheduled_start",
            name="ck_matches_scheduled_window_valid",
        ),
        CheckConstraint(
            "actual_end IS NULL OR actual_start IS NULL OR actual_end >= actual_start",
            name="ck_matches_actual_window_valid",
        ),
        Index("ix_matches_tournament_status", "tournament_id", "match_status"),
        Index("ix_matches_tournament_round", "tournament_id", "round_number"),
    )

    match_uid: Mapped[str] = mapped_column(
        String(20), unique=True, index=True, nullable=False, default=lambda: uuid.uuid4().hex[:12]
    )

    tournament_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tournaments.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    round_number: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    match_number: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    # ------------------------------------------------------------------
    # Room details. Password is stored so it can be re-published/edited by
    # the organizer; it is never exposed by the public read schema until
    # room_status == PUBLISHED (enforced in the service layer).
    # ------------------------------------------------------------------
    room_name: Mapped[Optional[str]] = mapped_column(String(150), nullable=True)
    room_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    room_password: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    room_status: Mapped[RoomStatus] = mapped_column(
        str_enum(RoomStatus, "match_room_status"),
        default=RoomStatus.NOT_CREATED,
        nullable=False,
        index=True,
    )
    room_published_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    match_status: Mapped[MatchStatus] = mapped_column(
        str_enum(MatchStatus, "match_status"),
        default=MatchStatus.DRAFT,
        nullable=False,
        index=True,
    )

    scheduled_start: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    scheduled_end: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    actual_start: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    actual_end: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # ------------------------------------------------------------------
    # Check-in configuration (Phase 7 §6).
    # ------------------------------------------------------------------
    check_in_opens_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    check_in_deadline: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    auto_disqualify_on_no_show: Mapped[bool] = mapped_column(
        Boolean, default=True, nullable=False
    )

    winner_team_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("teams.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    created_by: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    tournament: Mapped["Tournament"] = relationship(lazy="selectin")  # noqa: F821
    winner_team: Mapped[Optional["Team"]] = relationship(  # noqa: F821
        foreign_keys=[winner_team_id], lazy="selectin"
    )
    creator: Mapped[Optional["User"]] = relationship(  # noqa: F821
        foreign_keys=[created_by], lazy="selectin"
    )
    slots: Mapped[list["MatchParticipant"]] = relationship(  # noqa: F821
        back_populates="match", cascade="all, delete-orphan", lazy="selectin"
    )

    def __repr__(self) -> str:
        return (
            f"<Match id={self.id} tournament_id={self.tournament_id} "
            f"round={self.round_number} number={self.match_number} status={self.match_status}>"
        )
