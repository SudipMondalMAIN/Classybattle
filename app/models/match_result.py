"""
MatchResult model — Match Result & Winner Management System (Phase 11).

One active result row per Match (unique constraint on match_id). Editing
resubmits/updates this same row; a rejected result can be resubmitted by
transitioning back to SUBMITTED. Full history of every state change is
captured via the existing AuditService (entity="match_result"), rather
than a bespoke history table, so it is queried the same way audit trails
for every other module already are.
"""
import enum
import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import BaseModel
from app.database.types import PortableJSONB, str_enum


class MatchResultStatus(str, enum.Enum):
    SUBMITTED = "submitted"
    VERIFIED = "verified"
    APPROVED = "approved"
    REJECTED = "rejected"


# Explicit allowed forward transitions, mirroring the pattern used for
# MATCH_STATUS_TRANSITIONS / PRIZE_POOL_STATUS_TRANSITIONS.
MATCH_RESULT_STATUS_TRANSITIONS: dict[MatchResultStatus, set[MatchResultStatus]] = {
    MatchResultStatus.SUBMITTED: {MatchResultStatus.VERIFIED, MatchResultStatus.REJECTED},
    MatchResultStatus.VERIFIED: {MatchResultStatus.APPROVED, MatchResultStatus.REJECTED},
    MatchResultStatus.APPROVED: set(),
    MatchResultStatus.REJECTED: {MatchResultStatus.SUBMITTED},
}


class MatchResult(BaseModel):
    __tablename__ = "match_results"
    __table_args__ = (
        UniqueConstraint("match_id", name="uq_match_results_match_id"),
        Index("ix_match_results_tournament_status", "tournament_id", "status"),
    )

    match_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("matches.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # Denormalized for tournament-wide filtering/pagination without a join.
    tournament_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tournaments.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Freeform per-slot result data as submitted, e.g.:
    # [{"participant_id": "...", "score": 42, "placement": 1}, ...] or
    # [{"team_id": "...", "score": 10, "placement": 2}, ...]
    result_data: Mapped[list] = mapped_column(PortableJSONB, nullable=False)
    is_tie: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    status: Mapped[MatchResultStatus] = mapped_column(
        str_enum(MatchResultStatus, "match_result_status"),
        default=MatchResultStatus.SUBMITTED,
        nullable=False,
        index=True,
    )

    submitted_by: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    submitted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    verified_by: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    verified_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    approved_by: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    approved_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    rejected_by: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    rejected_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    rejection_reason: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)

    # Guards Phase 10 prize distribution from ever being triggered twice for
    # the same match result, even under concurrent approve retries.
    prize_distribution_triggered: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False
    )
    prize_distribution_triggered_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    match: Mapped["Match"] = relationship(lazy="selectin")  # noqa: F821
    tournament: Mapped["Tournament"] = relationship(lazy="selectin")  # noqa: F821
    winners: Mapped[list["MatchWinner"]] = relationship(  # noqa: F821
        back_populates="match_result",
        cascade="all, delete-orphan",
        lazy="selectin",
        order_by="MatchWinner.rank.asc()",
    )

    def __repr__(self) -> str:
        return (
            f"<MatchResult id={self.id} match_id={self.match_id} status={self.status}>"
        )
