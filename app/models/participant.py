"""
Participant model — Tournament Registration & Participants (Phase 5).
"""
import enum
import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Numeric,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import BaseModel


class RegistrationType(str, enum.Enum):
    SOLO = "solo"
    DUO = "duo"
    SQUAD = "squad"
    TEAM = "team"


class ParticipantStatus(str, enum.Enum):
    PENDING = "pending"
    CONFIRMED = "confirmed"
    CANCELLED = "cancelled"
    REJECTED = "rejected"
    CHECKED_IN = "checked_in"


class ParticipantPaymentStatus(str, enum.Enum):
    NOT_REQUIRED = "not_required"
    PENDING = "pending"
    PAID = "paid"
    FAILED = "failed"
    REFUNDED = "refunded"


# Explicit allowed forward transitions for participant status, mirroring the
# pattern used for TOURNAMENT_STATUS_TRANSITIONS.
PARTICIPANT_STATUS_TRANSITIONS: dict[ParticipantStatus, set[ParticipantStatus]] = {
    ParticipantStatus.PENDING: {
        ParticipantStatus.CONFIRMED,
        ParticipantStatus.REJECTED,
        ParticipantStatus.CANCELLED,
    },
    ParticipantStatus.CONFIRMED: {
        ParticipantStatus.CHECKED_IN,
        ParticipantStatus.CANCELLED,
    },
    ParticipantStatus.CHECKED_IN: {
        ParticipantStatus.CANCELLED,
    },
    ParticipantStatus.CANCELLED: set(),
    ParticipantStatus.REJECTED: set(),
}


class Participant(BaseModel):
    __tablename__ = "participants"
    __table_args__ = (
        UniqueConstraint(
            "tournament_id", "user_id", name="uq_participants_tournament_user"
        ),
        CheckConstraint("entry_fee_paid >= 0", name="ck_participants_entry_fee_non_negative"),
        Index("ix_participants_tournament_status", "tournament_id", "status"),
        Index("ix_participants_user_status", "user_id", "status"),
    )

    participant_uid: Mapped[str] = mapped_column(
        String(20), unique=True, index=True, nullable=False, default=lambda: uuid.uuid4().hex[:12]
    )

    tournament_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tournaments.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    game_profile_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("user_game_profiles.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )

    registration_type: Mapped[RegistrationType] = mapped_column(
        Enum(RegistrationType, name="participant_registration_type"),
        default=RegistrationType.SOLO,
        nullable=False,
    )
    team_name: Mapped[Optional[str]] = mapped_column(String(150), nullable=True)

    status: Mapped[ParticipantStatus] = mapped_column(
        Enum(ParticipantStatus, name="participant_status"),
        default=ParticipantStatus.PENDING,
        nullable=False,
        index=True,
    )

    payment_status: Mapped[ParticipantPaymentStatus] = mapped_column(
        Enum(ParticipantPaymentStatus, name="participant_payment_status"),
        default=ParticipantPaymentStatus.NOT_REQUIRED,
        nullable=False,
    )
    payment_reference: Mapped[Optional[str]] = mapped_column(String(150), nullable=True)
    entry_fee_paid: Mapped[float] = mapped_column(Numeric(10, 2), default=0, nullable=False)

    joined_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    cancelled_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    checked_in_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    tournament: Mapped["Tournament"] = relationship(lazy="selectin")  # noqa: F821
    user: Mapped["User"] = relationship(lazy="selectin")  # noqa: F821
    game_profile: Mapped["UserGameProfile"] = relationship(lazy="selectin")  # noqa: F821

    def __repr__(self) -> str:
        return f"<Participant id={self.id} tournament_id={self.tournament_id} user_id={self.user_id} status={self.status}>"
