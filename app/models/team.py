"""
Team model — Team System & Invite Management (Phase 6).
"""
import enum
import secrets
import uuid
from typing import Optional

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import BaseModel, ShortIdMixin
from app.database.types import str_enum


class TeamStatus(str, enum.Enum):
    FORMING = "forming"
    LOCKED = "locked"
    DISBANDED = "disbanded"


# Explicit allowed forward transitions, mirroring the pattern used for
# TOURNAMENT_STATUS_TRANSITIONS / PARTICIPANT_STATUS_TRANSITIONS.
TEAM_STATUS_TRANSITIONS: dict[TeamStatus, set[TeamStatus]] = {
    TeamStatus.FORMING: {TeamStatus.LOCKED, TeamStatus.DISBANDED},
    TeamStatus.LOCKED: {TeamStatus.FORMING, TeamStatus.DISBANDED},
    TeamStatus.DISBANDED: set(),
}


def generate_invite_code() -> str:
    """Cryptographically secure, human-friendly invite code (e.g. 8 chars,
    unambiguous alphabet — no 0/O/1/I confusion)."""
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    return "".join(secrets.choice(alphabet) for _ in range(8))


_RANDOM_TEAM_ADJECTIVES = [
    "Blazing", "Silent", "Rapid", "Iron", "Crimson", "Shadow", "Savage",
    "Frost", "Golden", "Rogue", "Phantom", "Storm", "Alpha", "Toxic",
    "Venom", "Titan", "Rebel", "Fierce", "Dark", "Royal",
]
_RANDOM_TEAM_NOUNS = [
    "Wolves", "Falcons", "Raiders", "Titans", "Warriors", "Reapers",
    "Hunters", "Ghosts", "Vipers", "Knights", "Dragons", "Legion",
    "Sharks", "Panthers", "Outlaws", "Guardians", "Phoenix", "Wraiths",
]


def generate_team_name() -> str:
    """Random default team name (e.g. 'Crimson Wolves') used when the
    creator does not supply a custom ``team_name``."""
    adjective = secrets.choice(_RANDOM_TEAM_ADJECTIVES)
    noun = secrets.choice(_RANDOM_TEAM_NOUNS)
    suffix = "".join(secrets.choice("0123456789") for _ in range(3))
    return f"{adjective} {noun} #{suffix}"


class Team(ShortIdMixin, BaseModel):
    __tablename__ = "teams"
    __table_args__ = (
        UniqueConstraint("invite_code", name="uq_teams_invite_code"),
        UniqueConstraint(
            "tournament_id", "team_name", name="uq_teams_tournament_team_name"
        ),
        CheckConstraint("team_size > 0", name="ck_teams_team_size_positive"),
        CheckConstraint(
            "current_members >= 0 AND current_members <= team_size",
            name="ck_teams_current_members_within_bounds",
        ),
        Index("ix_teams_tournament_status", "tournament_id", "status"),
    )

    team_uid: Mapped[str] = mapped_column(
        String(20), unique=True, index=True, nullable=False, default=lambda: uuid.uuid4().hex[:12]
    )

    tournament_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tournaments.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    team_name: Mapped[str] = mapped_column(String(150), nullable=False)

    captain_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    invite_code: Mapped[str] = mapped_column(
        String(16), unique=True, index=True, nullable=False, default=generate_invite_code
    )

    team_size: Mapped[int] = mapped_column(Integer, nullable=False)
    current_members: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    status: Mapped[TeamStatus] = mapped_column(
        str_enum(TeamStatus, "team_status"),
        default=TeamStatus.FORMING,
        nullable=False,
        index=True,
    )
    is_locked: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    tournament: Mapped["Tournament"] = relationship(lazy="selectin")  # noqa: F821
    captain: Mapped[Optional["User"]] = relationship(lazy="selectin")  # noqa: F821
    members: Mapped[list["TeamMember"]] = relationship(  # noqa: F821
        back_populates="team", cascade="all, delete-orphan", lazy="selectin"
    )

    def __repr__(self) -> str:
        return f"<Team id={self.id} tournament_id={self.tournament_id} name={self.team_name!r} status={self.status}>"