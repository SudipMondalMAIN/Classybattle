"""
MatchParticipant model — Match Team Assignment & Check-in System (Phase 7).

Represents a single slot within a Match: either a registered ``Team``
(Duo/Trio/Squad/tournament formats) or an individual ``Participant``
(Solo formats). One model backs team assignment (§2), check-in (§6) and
no-show handling (§7) so the three features share one consistent slot
lifecycle instead of duplicating state across tables.
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
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import BaseModel
from app.database.types import str_enum


class MatchAssignmentType(str, enum.Enum):
    REGISTERED = "registered"
    RANDOM = "random"
    MANUAL = "manual"
    AUTO = "auto"


class MatchCheckInStatus(str, enum.Enum):
    NOT_OPEN = "not_open"
    PENDING = "pending"
    CHECKED_IN = "checked_in"
    LATE_CHECKED_IN = "late_checked_in"
    NO_SHOW = "no_show"


# Explicit allowed forward transitions for a slot's check-in status.
MATCH_CHECKIN_TRANSITIONS: dict[MatchCheckInStatus, set[MatchCheckInStatus]] = {
    MatchCheckInStatus.NOT_OPEN: {MatchCheckInStatus.PENDING},
    MatchCheckInStatus.PENDING: {
        MatchCheckInStatus.CHECKED_IN,
        MatchCheckInStatus.LATE_CHECKED_IN,
        MatchCheckInStatus.NO_SHOW,
    },
    MatchCheckInStatus.CHECKED_IN: set(),
    MatchCheckInStatus.LATE_CHECKED_IN: set(),
    MatchCheckInStatus.NO_SHOW: {
        MatchCheckInStatus.CHECKED_IN,
        MatchCheckInStatus.LATE_CHECKED_IN,
    },
}


class MatchParticipant(BaseModel):
    __tablename__ = "match_participants"
    __table_args__ = (
        UniqueConstraint("match_id", "slot_number", name="uq_match_participants_match_slot"),
        UniqueConstraint(
            "match_id", "team_id", name="uq_match_participants_match_team"
        ),
        UniqueConstraint(
            "match_id", "participant_id", name="uq_match_participants_match_participant"
        ),
        CheckConstraint("slot_number > 0", name="ck_match_participants_slot_positive"),
        CheckConstraint(
            "(team_id IS NOT NULL) OR (participant_id IS NOT NULL) OR (match_team_id IS NOT NULL)",
            name="ck_match_participants_team_or_participant",
        ),
        Index("ix_match_participants_match_checkin", "match_id", "check_in_status"),
    )

    match_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("matches.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Exactly one of these two identifies who occupies this slot, depending
    # on whether the tournament is team-based (Duo/Trio/Squad) or solo.
    team_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("teams.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    # For recurring-schedule slots (Free Fire Clash Squad etc.) — points at
    # a per-slot MatchTeam instead of a per-tournament Team (see
    # app/models/match_team.py for why these are separate).
    match_team_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("match_teams.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    participant_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("participants.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )

    slot_number: Mapped[int] = mapped_column(Integer, nullable=False)

    assignment_type: Mapped[MatchAssignmentType] = mapped_column(
        str_enum(MatchAssignmentType, "match_assignment_type"),
        default=MatchAssignmentType.REGISTERED,
        nullable=False,
    )
    assigned_by: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    # ------------------------------------------------------------------
    # Check-in (§6) / no-show (§7) tracking.
    # ------------------------------------------------------------------
    check_in_status: Mapped[MatchCheckInStatus] = mapped_column(
        str_enum(MatchCheckInStatus, "match_check_in_status"),
        default=MatchCheckInStatus.NOT_OPEN,
        nullable=False,
        index=True,
    )
    checked_in_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    checked_in_by: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    is_organizer_override: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False
    )

    is_disqualified: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    disqualified_reason: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    replaced_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    match: Mapped["Match"] = relationship(back_populates="slots", lazy="selectin")  # noqa: F821
    team: Mapped[Optional["Team"]] = relationship(  # noqa: F821
        foreign_keys=[team_id], lazy="selectin"
    )
    match_team: Mapped[Optional["MatchTeam"]] = relationship(  # noqa: F821
        foreign_keys=[match_team_id], lazy="selectin"
    )
    participant: Mapped[Optional["Participant"]] = relationship(  # noqa: F821
        foreign_keys=[participant_id], lazy="selectin"
    )

    def __repr__(self) -> str:
        return (
            f"<MatchParticipant id={self.id} match_id={self.match_id} "
            f"team_id={self.team_id} participant_id={self.participant_id} "
            f"check_in={self.check_in_status}>"
        )
