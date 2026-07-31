"""
Live Match & Real-Time Tournament models — Phase 12.

Layered on top of the existing Match / Tournament lifecycle (Phases 7-11)
rather than replacing it: `Match.match_status` remains the single source
of truth for the *lifecycle* (draft -> ... -> live -> completed), while
`LiveMatch` tracks the *real-time* concerns for a match that is currently
being played (pause/resume, timers, round tracking) and
`LiveMatchEvent` / `LiveMatchScore` back the activity feed and live
leaderboard. `LiveTournamentState` tracks aggregate real-time tournament
progress (current round, live/completed match counts).
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
    Numeric,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import BaseModel
from app.database.types import PortableJSONB


class LiveMatchStatus(str, enum.Enum):
    NOT_STARTED = "not_started"
    LIVE = "live"
    PAUSED = "paused"
    ENDED = "ended"
    CANCELLED = "cancelled"


# Explicit allowed forward transitions, mirroring MATCH_STATUS_TRANSITIONS.
LIVE_MATCH_STATUS_TRANSITIONS: dict[LiveMatchStatus, set[LiveMatchStatus]] = {
    LiveMatchStatus.NOT_STARTED: {LiveMatchStatus.LIVE, LiveMatchStatus.CANCELLED},
    LiveMatchStatus.LIVE: {
        LiveMatchStatus.PAUSED,
        LiveMatchStatus.ENDED,
        LiveMatchStatus.CANCELLED,
    },
    LiveMatchStatus.PAUSED: {LiveMatchStatus.LIVE, LiveMatchStatus.CANCELLED},
    LiveMatchStatus.ENDED: set(),
    LiveMatchStatus.CANCELLED: set(),
}


class LiveMatchEventType(str, enum.Enum):
    MATCH_STARTED = "match_started"
    MATCH_PAUSED = "match_paused"
    MATCH_RESUMED = "match_resumed"
    MATCH_ENDED = "match_ended"
    MATCH_CANCELLED = "match_cancelled"
    ROUND_STARTED = "round_started"
    ROUND_ENDED = "round_ended"
    SCORE_UPDATE = "score_update"
    KILL = "kill"
    ELIMINATION = "elimination"
    OBJECTIVE = "objective"
    ANNOUNCEMENT = "announcement"
    OTHER = "other"


class LiveMatch(BaseModel):
    """One row per Match, created lazily on first live-match start.

    Timer math: elapsed active seconds = (now - started_at) - total_paused_seconds
    (minus the current in-progress pause span, if `status == PAUSED`).
    """

    __tablename__ = "live_matches"
    __table_args__ = (
        UniqueConstraint("match_id", name="uq_live_matches_match_id"),
        CheckConstraint(
            "total_paused_seconds >= 0", name="ck_live_matches_total_paused_non_negative"
        ),
        CheckConstraint("current_round > 0", name="ck_live_matches_current_round_positive"),
    )

    match_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("matches.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    tournament_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tournaments.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    status: Mapped[LiveMatchStatus] = mapped_column(
        Enum(LiveMatchStatus, name="live_match_status"),
        default=LiveMatchStatus.NOT_STARTED,
        nullable=False,
        index=True,
    )

    current_round: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    round_timer_seconds: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    round_started_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    started_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    paused_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    total_paused_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    ended_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    # Guards against the automatic-completion sweep double-firing.
    auto_completion_processed: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False
    )

    last_event_sequence: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    match: Mapped["Match"] = relationship(lazy="selectin")  # noqa: F821
    tournament: Mapped["Tournament"] = relationship(lazy="selectin")  # noqa: F821

    def __repr__(self) -> str:
        return f"<LiveMatch match_id={self.match_id} status={self.status}>"


class LiveMatchEvent(BaseModel):
    """Append-only match timeline / activity feed / kill log entry."""

    __tablename__ = "live_match_events"
    __table_args__ = (
        UniqueConstraint(
            "match_id", "client_event_id", name="uq_live_match_events_match_client_event"
        ),
        Index("ix_live_match_events_match_seq", "match_id", "sequence"),
        Index("ix_live_match_events_match_type", "match_id", "event_type"),
    )

    match_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("matches.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)

    event_type: Mapped[LiveMatchEventType] = mapped_column(
        Enum(LiveMatchEventType, name="live_match_event_type"),
        nullable=False,
        index=True,
    )
    round_number: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    team_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("teams.id", ondelete="SET NULL"), nullable=True
    )
    participant_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("participants.id", ondelete="SET NULL"), nullable=True
    )

    message: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    event_metadata: Mapped[Optional[dict]] = mapped_column(PortableJSONB, nullable=True)

    # Client-supplied idempotency token (e.g. a game-client generated UUID)
    # so a retried "log kill" request can never be recorded twice.
    client_event_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)

    created_by: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    team: Mapped[Optional["Team"]] = relationship(lazy="selectin")  # noqa: F821
    participant: Mapped[Optional["Participant"]] = relationship(lazy="selectin")  # noqa: F821

    def __repr__(self) -> str:
        return f"<LiveMatchEvent match_id={self.match_id} type={self.event_type} seq={self.sequence}>"


class LiveMatchScore(BaseModel):
    """Current live score for one team/participant within a match — one
    row per (match, team) or (match, participant), upserted on every
    score update so the leaderboard is always a cheap indexed read."""

    __tablename__ = "live_match_scores"
    __table_args__ = (
        UniqueConstraint("match_id", "team_id", name="uq_live_match_scores_match_team"),
        UniqueConstraint(
            "match_id", "participant_id", name="uq_live_match_scores_match_participant"
        ),
        CheckConstraint(
            "(team_id IS NOT NULL) OR (participant_id IS NOT NULL)",
            name="ck_live_match_scores_owner_present",
        ),
        Index("ix_live_match_scores_match_score", "match_id", "score"),
    )

    match_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("matches.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    team_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("teams.id", ondelete="CASCADE"), nullable=True
    )
    participant_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("participants.id", ondelete="CASCADE"), nullable=True
    )

    kills: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    score: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    rank: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    extra_stats: Mapped[Optional[dict]] = mapped_column(PortableJSONB, nullable=True)

    last_updated_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    team: Mapped[Optional["Team"]] = relationship(lazy="selectin")  # noqa: F821
    participant: Mapped[Optional["Participant"]] = relationship(lazy="selectin")  # noqa: F821

    def __repr__(self) -> str:
        return f"<LiveMatchScore match_id={self.match_id} score={self.score}>"


class LiveTournamentStatus(str, enum.Enum):
    NOT_STARTED = "not_started"
    LIVE = "live"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class LiveTournamentState(BaseModel):
    """One row per Tournament tracking real-time progress: current round
    and live/completed match counters, updated atomically by
    LiveTournamentService whenever a match starts/ends."""

    __tablename__ = "live_tournament_states"
    __table_args__ = (
        UniqueConstraint("tournament_id", name="uq_live_tournament_states_tournament_id"),
        CheckConstraint("current_round > 0", name="ck_live_tournament_states_round_positive"),
    )

    tournament_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tournaments.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    status: Mapped[LiveTournamentStatus] = mapped_column(
        Enum(LiveTournamentStatus, name="live_tournament_status"),
        default=LiveTournamentStatus.NOT_STARTED,
        nullable=False,
        index=True,
    )

    current_round: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    total_rounds: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    total_matches: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    live_matches: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    completed_matches: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    last_progressed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    tournament: Mapped["Tournament"] = relationship(lazy="selectin")  # noqa: F821

    def __repr__(self) -> str:
        return f"<LiveTournamentState tournament_id={self.tournament_id} round={self.current_round}>"
