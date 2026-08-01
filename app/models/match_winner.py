"""
MatchWinner model — Match Result & Winner Management System (Phase 11).

One row per (match, rank). Mirrors the "either a Team or a Participant"
slot pattern used by MatchParticipant so the same model backs both Solo
and Team match formats, single-winner and multi-winner/tie scenarios
(ties share the same rank across multiple rows).
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
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import BaseModel
from app.database.types import str_enum


class WinnerAssignmentSource(str, enum.Enum):
    AUTOMATIC = "automatic"
    MANUAL = "manual"


class MatchWinner(BaseModel):
    __tablename__ = "match_winners"
    __table_args__ = (
        UniqueConstraint("match_id", "rank", "team_id", name="uq_match_winners_match_rank_team"),
        UniqueConstraint(
            "match_id", "rank", "participant_id", name="uq_match_winners_match_rank_participant"
        ),
        UniqueConstraint(
            "match_id", "team_id", name="uq_match_winners_match_team"
        ),
        UniqueConstraint(
            "match_id", "participant_id", name="uq_match_winners_match_participant"
        ),
        CheckConstraint("rank > 0", name="ck_match_winners_rank_positive"),
        CheckConstraint(
            "(team_id IS NOT NULL) OR (participant_id IS NOT NULL)",
            name="ck_match_winners_team_or_participant",
        ),
        Index("ix_match_winners_match_rank", "match_id", "rank"),
    )

    match_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("matches.id", ondelete="CASCADE"), nullable=False, index=True
    )
    match_result_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("match_results.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    tournament_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tournaments.id", ondelete="CASCADE"), nullable=False, index=True
    )

    team_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("teams.id", ondelete="CASCADE"), nullable=True, index=True
    )
    participant_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("participants.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )

    rank: Mapped[int] = mapped_column(Integer, nullable=False)
    is_tie: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    assignment_source: Mapped[WinnerAssignmentSource] = mapped_column(
        str_enum(WinnerAssignmentSource, "winner_assignment_source"),
        default=WinnerAssignmentSource.AUTOMATIC,
        nullable=False,
    )
    is_manual_override: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    declared_by: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    declared_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    match: Mapped["Match"] = relationship(lazy="selectin")  # noqa: F821
    match_result: Mapped["MatchResult"] = relationship(  # noqa: F821
        back_populates="winners", lazy="selectin"
    )
    team: Mapped[Optional["Team"]] = relationship(foreign_keys=[team_id], lazy="selectin")  # noqa: F821
    participant: Mapped[Optional["Participant"]] = relationship(  # noqa: F821
        foreign_keys=[participant_id], lazy="selectin"
    )

    def __repr__(self) -> str:
        return (
            f"<MatchWinner id={self.id} match_id={self.match_id} rank={self.rank} "
            f"team_id={self.team_id} participant_id={self.participant_id}>"
        )
