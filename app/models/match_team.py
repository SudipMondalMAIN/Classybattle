"""
MatchTeam / MatchTeamMember — per-slot teams for recurring-schedule
matches (Free Fire Clash Squad style 1v1/2v2/3v3/4v4).

Unlike `Team` (Phase 6), which is scoped to a whole Tournament and
allows only one team per user per tournament, a `MatchTeam` is scoped
to a single `Match` (= one time slot, e.g. "Free Fire Clash Squad,
2v2, 8:00 PM"). This lets the same user form a fresh team with
different friends in a different slot every day, which is exactly how
Clash Squad join-with-friends-or-random is meant to work.
"""
import enum
import uuid
from typing import Optional

from sqlalchemy import (
    Boolean,
    CheckConstraint,
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
from app.models.team import generate_invite_code


class MatchTeamStatus(str, enum.Enum):
    FORMING = "forming"
    LOCKED = "locked"
    DISBANDED = "disbanded"


class MatchTeam(BaseModel):
    __tablename__ = "match_teams"
    __table_args__ = (
        UniqueConstraint("invite_code", name="uq_match_teams_invite_code"),
        CheckConstraint("team_size > 0", name="ck_match_teams_team_size_positive"),
        CheckConstraint(
            "current_members >= 0 AND current_members <= team_size",
            name="ck_match_teams_current_members_within_bounds",
        ),
        Index("ix_match_teams_match_status", "match_id", "status"),
    )

    match_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("matches.id", ondelete="CASCADE"),
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

    # team_format mirrors Match.team_format (e.g. "2v2") — duplicated here
    # so a MatchTeam's own size is self-describing without a join.
    team_format: Mapped[str] = mapped_column(String(10), nullable=False)
    team_size: Mapped[int] = mapped_column(Integer, nullable=False)
    current_members: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    # True when the team was started by the "random matchmaking" join
    # path (auto-fills with whoever else picks random for this slot),
    # as opposed to a friend group that used create/invite.
    is_random: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)

    status: Mapped[MatchTeamStatus] = mapped_column(
        str_enum(MatchTeamStatus, "match_team_status"),
        default=MatchTeamStatus.FORMING,
        nullable=False,
        index=True,
    )

    match: Mapped["Match"] = relationship(lazy="selectin")  # noqa: F821
    captain: Mapped[Optional["User"]] = relationship(lazy="selectin")  # noqa: F821
    members: Mapped[list["MatchTeamMember"]] = relationship(
        back_populates="match_team", cascade="all, delete-orphan", lazy="selectin"
    )

    def __repr__(self) -> str:
        return (
            f"<MatchTeam id={self.id} match_id={self.match_id} "
            f"format={self.team_format} status={self.status}>"
        )


class MatchTeamMember(BaseModel):
    __tablename__ = "match_team_members"
    __table_args__ = (
        UniqueConstraint("match_team_id", "user_id", name="uq_match_team_members_team_user"),
    )

    match_team_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("match_teams.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    match_team: Mapped["MatchTeam"] = relationship(back_populates="members", lazy="selectin")
    user: Mapped["User"] = relationship(lazy="selectin")  # noqa: F821

    def __repr__(self) -> str:
        return f"<MatchTeamMember match_team_id={self.match_team_id} user_id={self.user_id}>"
