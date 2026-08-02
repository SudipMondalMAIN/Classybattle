"""
Tournament model — core entity for the Tournament module (Phase 2).
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
    Text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import BaseModel
from app.database.types import str_enum


class TournamentStatus(str, enum.Enum):
    DRAFT = "draft"
    PUBLISHED = "published"
    REGISTRATION_OPEN = "registration_open"
    REGISTRATION_CLOSED = "registration_closed"
    LIVE = "live"
    COMPLETED = "completed"
    ARCHIVED = "archived"
    CANCELLED = "cancelled"


class TournamentVisibility(str, enum.Enum):
    PUBLIC = "public"
    PRIVATE = "private"
    UNLISTED = "unlisted"


class TeamRegistrationMode(str, enum.Enum):
    """How participants are grouped into teams for a tournament (Phase 6)."""

    SOLO = "solo"
    TEAM_INVITE = "team_invite"
    AUTO_RANDOM = "auto_random"


# Explicit allowed forward transitions. Kept as data (not scattered `if`
# chains) so the service layer and any future admin UI can introspect it.
TOURNAMENT_STATUS_TRANSITIONS: dict[TournamentStatus, set[TournamentStatus]] = {
    TournamentStatus.DRAFT: {TournamentStatus.PUBLISHED, TournamentStatus.CANCELLED},
    TournamentStatus.PUBLISHED: {
        TournamentStatus.REGISTRATION_OPEN,
        TournamentStatus.CANCELLED,
    },
    TournamentStatus.REGISTRATION_OPEN: {
        TournamentStatus.REGISTRATION_CLOSED,
        TournamentStatus.CANCELLED,
    },
    TournamentStatus.REGISTRATION_CLOSED: {
        TournamentStatus.LIVE,
        TournamentStatus.REGISTRATION_OPEN,
        TournamentStatus.CANCELLED,
    },
    TournamentStatus.LIVE: {TournamentStatus.COMPLETED, TournamentStatus.CANCELLED},
    TournamentStatus.COMPLETED: {TournamentStatus.ARCHIVED},
    TournamentStatus.ARCHIVED: set(),
    TournamentStatus.CANCELLED: {TournamentStatus.ARCHIVED},
}


class Tournament(BaseModel):
    __tablename__ = "tournaments"
    __table_args__ = (
        CheckConstraint("entry_fee >= 0", name="ck_tournaments_entry_fee_non_negative"),
        CheckConstraint("prize_pool >= 0", name="ck_tournaments_prize_pool_non_negative"),
        CheckConstraint("max_players > 0", name="ck_tournaments_max_players_positive"),
        CheckConstraint(
            "current_players >= 0 AND current_players <= max_players",
            name="ck_tournaments_current_players_within_bounds",
        ),
        CheckConstraint(
            "registration_end > registration_start",
            name="ck_tournaments_registration_window_valid",
        ),
        CheckConstraint(
            "tournament_end > tournament_start",
            name="ck_tournaments_play_window_valid",
        ),
        CheckConstraint(
            "team_size > 0", name="ck_tournaments_team_size_positive"
        ),
        CheckConstraint(
            "max_teams IS NULL OR max_teams > 0",
            name="ck_tournaments_max_teams_positive",
        ),
        Index("ix_tournaments_status_visibility", "status", "visibility"),
        Index("ix_tournaments_game_status", "game_id", "status"),
    )

    tournament_uid: Mapped[str] = mapped_column(
        String(20), unique=True, index=True, nullable=False, default=lambda: uuid.uuid4().hex[:12]
    )

    title: Mapped[str] = mapped_column(String(200), nullable=False)
    slug: Mapped[str] = mapped_column(String(230), unique=True, index=True, nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    rules: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    game_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("games.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )

    # Phase 7.5: promoted from free-form String(50) identifiers to proper
    # FK-backed references now that GameMode/Map lookup tables exist
    # (Phases 3-4). ON DELETE SET NULL keeps a tournament intact even if
    # its mode/map is later retired.
    mode_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("game_modes.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    map_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("maps.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    banner_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    cover_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)

    organizer: Mapped[str] = mapped_column(String(150), nullable=False)

    entry_fee: Mapped[Decimal] = mapped_column(Numeric(10, 2), default=0, nullable=False)
    prize_pool: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0, nullable=False)

    max_players: Mapped[int] = mapped_column(Integer, nullable=False)
    current_players: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    registration_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    registration_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    tournament_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    tournament_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    status: Mapped[TournamentStatus] = mapped_column(
        str_enum(TournamentStatus, "tournament_status"),
        default=TournamentStatus.DRAFT,
        nullable=False,
        index=True,
    )
    visibility: Mapped[TournamentVisibility] = mapped_column(
        str_enum(TournamentVisibility, "tournament_visibility"),
        default=TournamentVisibility.PUBLIC,
        nullable=False,
    )
    is_featured: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # ------------------------------------------------------------------
    # Team registration settings (Phase 6).
    # ------------------------------------------------------------------
    registration_mode: Mapped[TeamRegistrationMode] = mapped_column(
        str_enum(TeamRegistrationMode, "tournament_registration_mode"),
        default=TeamRegistrationMode.SOLO,
        nullable=False,
    )
    team_size: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    max_teams: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    created_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    game: Mapped["Game"] = relationship(lazy="selectin")  # noqa: F821
    mode: Mapped[Optional["GameMode"]] = relationship(lazy="selectin")  # noqa: F821
    map: Mapped[Optional["Map"]] = relationship(lazy="selectin")  # noqa: F821
    creator: Mapped[Optional["User"]] = relationship(lazy="selectin")  # noqa: F821

    def __repr__(self) -> str:
        return f"<Tournament id={self.id} slug={self.slug} status={self.status}>"