"""
TournamentParticipant model — Tournament Team Assignment & Check-in System (Phase 7).

Represents a single slot within a Tournament: either a registered ``Team``
(Duo/Trio/Squad/tournament formats) or an individual ``Participant``
(Solo formats). One model backs team assignment (§2), check-in (§6) and
no-show handling (§7) so the three features share one consistent slot
lifecycle instead of duplicating state across tables.
"""
import enum
import uuid
from datetime import datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import BaseModel
from app.database.types import str_enum


class TournamentAssignmentType(str, enum.Enum):
    REGISTERED = "registered"
    RANDOM = "random"
    MANUAL = "manual"
    AUTO = "auto"


class TournamentCheckInStatus(str, enum.Enum):
    NOT_OPEN = "not_open"
    PENDING = "pending"
    CHECKED_IN = "checked_in"
    LATE_CHECKED_IN = "late_checked_in"
    NO_SHOW = "no_show"


# Explicit allowed forward transitions for a slot's check-in status.
TOURNAMENT_CHECKIN_TRANSITIONS: dict[TournamentCheckInStatus, set[TournamentCheckInStatus]] = {
    TournamentCheckInStatus.NOT_OPEN: {TournamentCheckInStatus.PENDING},
    TournamentCheckInStatus.PENDING: {
        TournamentCheckInStatus.CHECKED_IN,
        TournamentCheckInStatus.LATE_CHECKED_IN,
        TournamentCheckInStatus.NO_SHOW,
    },
    TournamentCheckInStatus.CHECKED_IN: set(),
    TournamentCheckInStatus.LATE_CHECKED_IN: set(),
    TournamentCheckInStatus.NO_SHOW: {
        TournamentCheckInStatus.CHECKED_IN,
        TournamentCheckInStatus.LATE_CHECKED_IN,
    },
}


class TournamentParticipant(BaseModel):
    __tablename__ = "tournament_participants"
    __table_args__ = (
        UniqueConstraint("tournament_id", "slot_number", name="uq_tournament_participants_match_slot"),
        UniqueConstraint(
            "tournament_id", "team_id", name="uq_tournament_participants_match_team"
        ),
        UniqueConstraint(
            "tournament_id", "participant_id", name="uq_tournament_participants_match_participant"
        ),
        CheckConstraint("slot_number > 0", name="ck_tournament_participants_slot_positive"),
        CheckConstraint(
            "(team_id IS NOT NULL) OR (participant_id IS NOT NULL) OR (tournament_team_id IS NOT NULL)",
            name="ck_tournament_participants_team_or_participant",
        ),
        Index("ix_tournament_participants_match_checkin", "tournament_id", "check_in_status"),
    )

    tournament_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tournaments.id", ondelete="CASCADE"),
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
    # a per-slot TournamentTeam instead of a per-tournament Team (see
    # app/models/tournament_team.py for why these are separate).
    tournament_team_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tournament_teams.id", ondelete="CASCADE"),
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

    assignment_type: Mapped[TournamentAssignmentType] = mapped_column(
        str_enum(TournamentAssignmentType, "tournament_assignment_type"),
        default=TournamentAssignmentType.REGISTERED,
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
    check_in_status: Mapped[TournamentCheckInStatus] = mapped_column(
        str_enum(TournamentCheckInStatus, "tournament_check_in_status"),
        default=TournamentCheckInStatus.NOT_OPEN,
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

    # ------------------------------------------------------------------
    # Admin match-details page: result entry (Raj's flow) — how many
    # kills this player got, whether Admin declared them a winner, and
    # the winning amount Admin has paid out (credited to wallet).
    # ------------------------------------------------------------------
    kills: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    is_winner: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)
    winning_amount: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(12, 2), nullable=True
    )
    winning_paid_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    tournament: Mapped["Tournament"] = relationship(back_populates="slots", lazy="selectin")  # noqa: F821
    team: Mapped[Optional["Team"]] = relationship(  # noqa: F821
        foreign_keys=[team_id], lazy="selectin"
    )
    tournament_team: Mapped[Optional["TournamentTeam"]] = relationship(  # noqa: F821
        foreign_keys=[tournament_team_id], lazy="selectin"
    )
    participant: Mapped[Optional["Participant"]] = relationship(  # noqa: F821
        foreign_keys=[participant_id], lazy="selectin"
    )

    def __repr__(self) -> str:
        return (
            f"<TournamentParticipant id={self.id} tournament_id={self.tournament_id} "
            f"team_id={self.team_id} participant_id={self.participant_id} "
            f"check_in={self.check_in_status}>"
        )
