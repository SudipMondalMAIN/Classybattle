"""
Tournament model — core entity for the Tournament module.

Match-refactor: Tournament is now the joinable/playable unit itself
(the Match layer has been removed). Room publish info
(room_id/room_password/published_at/auto_complete_at), formerly on
Match/LiveMatch, now lives directly on Tournament.
"""
import enum
import uuid
from datetime import datetime, time
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
    Text,
    Time,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import BaseModel, ShortIdMixin
from app.database.types import PortableJSONB, str_enum


class TournamentStatus(str, enum.Enum):
    SCHEDULED = "scheduled"    # user can join anytime while in this state
    LIVE = "live"              # auto-set the moment admin publishes room_id/room_password
    COMPLETED = "completed"    # auto-set 40 minutes after room publish (published_at + 40min)
    CANCELLED = "cancelled"    # admin can cancel from any state, any time


class TournamentVisibility(str, enum.Enum):
    PUBLIC = "public"
    PRIVATE = "private"
    UNLISTED = "unlisted"


class TeamRegistrationMode(str, enum.Enum):
    """How participants are grouped into teams for a tournament (Phase 6)."""

    SOLO = "solo"
    TEAM_INVITE = "team_invite"
    AUTO_RANDOM = "auto_random"


class PrizeType(str, enum.Enum):
    """How a tournament/schedule pays out winners (Raj's prize-type flow).

    RANK: classic rank-based prize breakdown (1st/2nd/3rd... amounts),
        stored in `rank_prize_rules`.
    PER_KILL: flat amount paid per confirmed kill, stored in
        `per_kill_amount` -- payout = kills * per_kill_amount.
    WIN: flat bonus paid only to whoever is marked the winner, stored in
        `win_amount`.
    """

    RANK = "rank"
    PER_KILL = "per_kill"
    WIN = "win"


class ScheduleCategory(str, enum.Enum):
    """Simplified per-game category for auto-generated daily tournament
    schedules: every Game can have any number of schedules per category —
    SOLO (classic/battle-royale, join alone), DUO (fixed 2-player team),
    and SQUAD (Clash-Squad style, join as a fixed-size team, size
    admin-configurable). No map/mode picking needed; Admin only
    configures tournaments-per-day, per-tournament time, entry fee and
    prize pool for each.

    The CS_*/LW_*/BR_SURVIVE values below are additional named formats
    (Clash Squad 1v1/Headshot/4v4, Lone Wolf 1v1/Headshot, Battle Royale
    Survival) -- distinct browse-page/filter labels, same join mechanics
    as their team-size counterpart (join/register flow doesn't branch on
    these; only the "Browse Tournaments" filter and home-screen category
    boxes read this value).
    """

    SOLO = "solo"
    DUO = "duo"
    SQUAD = "squad"
    CS_1V1 = "cs_1v1"
    CS_HEAD = "cs_head"
    CS_4V4 = "cs_4v4"
    LW_1V1 = "lw_1v1"
    LW_HEAD = "lw_head"
    BR_SURVIVE = "br_survive"


class TeamFormat(str, enum.Enum):
    """Player-vs-player team size for Clash-Squad-style formats.

    Only relevant when the schedule's game mode supports variable team
    sizes (e.g. Free Fire Clash Squad: 1v1/2v2/3v3/4v4). Classic/Battle
    Royale style modes (Free Fire Classic, BGMI Classic/Squad) ignore
    this and use SOLO / fixed squad sizing from GameMode instead.
    """

    SOLO = "solo"
    ONE_V_ONE = "1v1"
    TWO_V_TWO = "2v2"
    THREE_V_THREE = "3v3"
    FOUR_V_FOUR = "4v4"


# Explicit allowed forward transitions. Kept as data (not scattered `if`
# chains) so the service layer and any future admin UI can introspect it.
TOURNAMENT_STATUS_TRANSITIONS: dict[TournamentStatus, set[TournamentStatus]] = {
    TournamentStatus.SCHEDULED: {TournamentStatus.LIVE, TournamentStatus.CANCELLED},
    TournamentStatus.LIVE: {TournamentStatus.COMPLETED, TournamentStatus.CANCELLED},
    TournamentStatus.COMPLETED: set(),
    TournamentStatus.CANCELLED: set(),
}


class Tournament(ShortIdMixin, BaseModel):
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
            "team_size > 0", name="ck_tournaments_team_size_positive"
        ),
        CheckConstraint(
            "max_teams IS NULL OR max_teams > 0",
            name="ck_tournaments_max_teams_positive",
        ),
        CheckConstraint(
            "per_kill_amount IS NULL OR per_kill_amount >= 0",
            name="ck_tournaments_per_kill_amount_non_negative",
        ),
        CheckConstraint(
            "win_amount IS NULL OR win_amount >= 0",
            name="ck_tournaments_win_amount_non_negative",
        ),
        Index("ix_tournaments_status_visibility", "status", "visibility"),
        Index("ix_tournaments_game_status", "game_id", "status"),
        Index("ix_tournaments_status_auto_complete", "status", "auto_complete_at"),
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

    # ------------------------------------------------------------------
    # Prize type config (Raj's flow). Set at schedule-creation time,
    # editable afterwards same as entry_fee/prize_pool -- every slot
    # generated from a schedule inherits its template's current values.
    # Exactly one of the three payout fields below is used, based on
    # `prize_type`:
    #   RANK      -> rank_prize_rules   (e.g. [{"rank":1,"amount":500}, ...])
    #   PER_KILL  -> per_kill_amount    (₹ paid per confirmed kill)
    #   WIN       -> win_amount         (flat ₹ paid to the declared winner)
    # ------------------------------------------------------------------
    prize_type: Mapped["PrizeType"] = mapped_column(
        str_enum(PrizeType, "prize_type"), default=PrizeType.RANK, nullable=False
    )
    rank_prize_rules: Mapped[Optional[list]] = mapped_column(
        PortableJSONB, nullable=True,
        comment="Used when prize_type='rank'. List of {'rank': int, 'amount': number}.",
    )
    per_kill_amount: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(10, 2), nullable=True,
        comment="Used when prize_type='per_kill'. ₹ paid per confirmed kill.",
    )
    win_amount: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(10, 2), nullable=True,
        comment="Used when prize_type='win'. Flat ₹ paid to the declared winner.",
    )

    max_players: Mapped[int] = mapped_column(Integer, nullable=False)
    current_players: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    status: Mapped[TournamentStatus] = mapped_column(
        str_enum(TournamentStatus, "tournament_status"),
        default=TournamentStatus.SCHEDULED,
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
    # Room / live info — merged in from Match/LiveMatch. Publishing the
    # room (room_id + room_password) auto-flips status -> LIVE and stamps
    # published_at / auto_complete_at (published_at + 40 minutes). A
    # background scheduler tick flips status -> COMPLETED once
    # auto_complete_at has passed (queried directly off this indexed
    # pair, no per-row recomputation needed).
    # ------------------------------------------------------------------
    room_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    room_password: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    published_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    auto_complete_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    # Compare-and-swap gate for CustomMatchClaimService's 1v1 auto-
    # resolve flow (see migration 0045 for why: row locks and advisory
    # locks both failed to serialize concurrent "I Lost" submissions in
    # production). Whichever request's
    # "UPDATE ... WHERE custom_result_resolving_at IS NULL" actually
    # affects this row wins the right to decide the match outcome; a
    # concurrent request sees 0 rows affected and backs off. Postgres
    # enforces this atomically at the row level regardless of pooling.
    custom_result_resolving_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Absolute (UTC-stored) scheduled kickoff for this slot, e.g. an admin
    # slot time of "18:00" IST on 2026-08-15 is stored here as the
    # equivalent UTC instant. Set once at slot-generation time (see
    # SlotGeneratorService) for admin/schedule-generated tournaments; left
    # null for one-off custom tournaments, which join instantly and have
    # no fixed kickoff. This is the single source of truth for
    # chronological ("10:00, then 10:30, then 11:00...") ordering in the
    # tournament list -- created_at reflects generation/batch order, not
    # slot time, and must not be used for display ordering.
    starts_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True, index=True)

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

    # ------------------------------------------------------------------
    # Recurring daily schedule config. When is_recurring_schedule is
    # True, this row is not a single bracket event but a template that
    # SlotGeneratorService uses to stamp out one `Tournament` (= one
    # join-able slot, e.g. "Free Fire Classic 10:30 AM") every
    # `slot_interval_minutes` between daily_start_time and
    # daily_end_time, for every day. Join is instant while
    # status == SCHEDULED and slots are available — no registration
    # window.
    # ------------------------------------------------------------------
    is_recurring_schedule: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False, index=True
    )
    daily_start_time: Mapped[Optional[time]] = mapped_column(Time, nullable=True)
    daily_end_time: Mapped[Optional[time]] = mapped_column(Time, nullable=True)
    slot_interval_minutes: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    # Which team formats this schedule offers at join time (e.g. Free
    # Fire Clash Squad -> ["1v1","2v2","3v3","4v4"]; BGMI -> ["solo"] or
    # left null since BGMI has no variable-format team feature).
    allowed_team_formats: Mapped[Optional[list[str]]] = mapped_column(
        PortableJSONB, nullable=True
    )

    last_generated_on: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="Last date slots were auto-generated for this schedule, to keep generation idempotent.",
    )

    # ------------------------------------------------------------------
    # Simplified schedule config (Raj's flow). A schedule is always
    # exactly one of SOLO or SQUAD per Game — no map/mode picking.
    # `daily_slot_times` is the source of truth for how many tournaments
    # get generated per day and at what time: Admin can add/remove/edit
    # entries freely, and can edit an individual generated Tournament's
    # time/fee/prize afterwards too (entry_fee / prize_pool override the
    # schedule default).
    # ------------------------------------------------------------------
    category: Mapped[Optional[ScheduleCategory]] = mapped_column(
        str_enum(ScheduleCategory, "schedule_category"), nullable=True, index=True
    )
    squad_size: Mapped[int] = mapped_column(
        Integer, default=4, nullable=False,
        comment="Players per squad when category=SQUAD (e.g. 4 for a 4v4 Clash Squad tournament). Ignored for SOLO.",
    )
    daily_slot_times: Mapped[Optional[list[str]]] = mapped_column(
        PortableJSONB, nullable=True,
        comment="List of 'HH:MM' (24h, UTC) strings, one per tournament generated each day. len() = tournaments/day.",
    )

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
    slots: Mapped[list["TournamentParticipant"]] = relationship(  # noqa: F821
        back_populates="tournament", cascade="all, delete-orphan", lazy="selectin"
    )

    def __repr__(self) -> str:
        return f"<Tournament id={self.id} slug={self.slug} status={self.status}>"