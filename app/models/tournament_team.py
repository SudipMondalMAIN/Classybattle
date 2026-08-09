"""
TournamentTeam / TournamentTeamMember — per-slot teams for recurring-schedule
matches (Free Fire Clash Squad style 1v1/2v2/3v3/4v4).

Unlike `Team` (Phase 6), which is scoped to a whole Tournament and
allows only one team per user per tournament, a `TournamentTeam` is scoped
to a single `Tournament` (= one time slot, e.g. "Free Fire Clash Squad,
2v2, 8:00 PM"). This lets the same user form a fresh team with
different friends in a different slot every day, which is exactly how
Clash Squad join-with-friends-or-random is meant to work.
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
from app.models.team import generate_invite_code


class TournamentTeamStatus(str, enum.Enum):
    FORMING = "forming"
    LOCKED = "locked"
    DISBANDED = "disbanded"


class TournamentTeam(BaseModel):
    __tablename__ = "tournament_teams"
    __table_args__ = (
        UniqueConstraint("invite_code", name="uq_tournament_teams_invite_code"),
        CheckConstraint("team_size > 0", name="ck_tournament_teams_team_size_positive"),
        CheckConstraint(
            "current_members >= 0 AND current_members <= team_size",
            name="ck_tournament_teams_current_members_within_bounds",
        ),
        Index("ix_tournament_teams_tournament_status", "tournament_id", "status"),
    )

    tournament_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tournaments.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    team_name: Mapped[Optional[str]] = mapped_column(String(150), nullable=True)
    captain_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    invite_code: Mapped[str] = mapped_column(
        String(16), unique=True, index=True, nullable=False, default=generate_invite_code
    )

    # team_format mirrors Tournament.team_format (e.g. "2v2") — duplicated here
    # so a TournamentTeam's own size is self-describing without a join.
    team_format: Mapped[str] = mapped_column(String(10), nullable=False)
    team_size: Mapped[int] = mapped_column(Integer, nullable=False)
    current_members: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    # True when the team was started by the "random matchmaking" join
    # path (auto-fills with whoever else picks random for this slot),
    # as opposed to a friend group that used create/invite.
    is_random: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)

    status: Mapped[TournamentTeamStatus] = mapped_column(
        str_enum(TournamentTeamStatus, "tournament_team_status"),
        default=TournamentTeamStatus.FORMING,
        nullable=False,
        index=True,
    )

    tournament: Mapped["Tournament"] = relationship(lazy="selectin")  # noqa: F821
    captain: Mapped[Optional["User"]] = relationship(lazy="selectin")  # noqa: F821
    members: Mapped[list["TournamentTeamMember"]] = relationship(
        back_populates="tournament_team", cascade="all, delete-orphan", lazy="selectin"
    )

    def __repr__(self) -> str:
        return (
            f"<TournamentTeam id={self.id} tournament_id={self.tournament_id} "
            f"format={self.team_format} status={self.status}>"
        )


class TournamentTeamMember(BaseModel):
    __tablename__ = "tournament_team_members"
    __table_args__ = (
        UniqueConstraint("tournament_team_id", "user_id", name="uq_tournament_team_members_team_user"),
    )

    tournament_team_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tournament_teams.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    tournament_team: Mapped["TournamentTeam"] = relationship(back_populates="members", lazy="selectin")
    user: Mapped["User"] = relationship(lazy="selectin")  # noqa: F821

    # ------------------------------------------------------------------
    # Admin match-details page: same per-player result fields as
    # MatchParticipant, but scoped to one squad member (a squad match's
    # MatchParticipant row represents the whole team, not one user).
    # ------------------------------------------------------------------
    kills: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    is_winner: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)
    rank: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    winning_amount: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 2), nullable=True)
    winning_paid_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    def __repr__(self) -> str:
        return f"<TournamentTeamMember tournament_team_id={self.tournament_team_id} user_id={self.user_id}>"
