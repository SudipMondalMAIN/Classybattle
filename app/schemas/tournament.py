"""
Tournament Pydantic schemas.

Match-refactor: Tournament is now the joinable/playable unit itself.
No registration_start/registration_end/tournament_start/tournament_end
windows -- join is instant while status == SCHEDULED and slots are
available. Room publish info (room_id/room_password/published_at/
auto_complete_at) lives directly on Tournament.
"""
from datetime import datetime
from decimal import Decimal
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models.tournament import (
    PrizeType,
    ScheduleCategory,
    TeamRegistrationMode,
    TournamentStatus,
    TournamentVisibility,
)
from app.schemas.schedule import RankPrizeRule


class TournamentCreate(BaseModel):
    title: str = Field(..., min_length=3, max_length=200)
    description: Optional[str] = Field(None, max_length=5000)
    rules: Optional[str] = Field(None, max_length=5000)
    game_id: UUID
    mode_id: Optional[UUID] = None
    map_id: Optional[UUID] = None
    organizer: str = Field(..., min_length=2, max_length=150)
    entry_fee: Decimal = Field(default=Decimal("0"), ge=0)
    prize_pool: Decimal = Field(default=Decimal("0"), ge=0)
    max_players: int = Field(..., gt=0, le=100000)
    visibility: TournamentVisibility = TournamentVisibility.PUBLIC
    is_featured: bool = False
    registration_mode: TeamRegistrationMode = TeamRegistrationMode.SOLO
    team_size: int = Field(default=1, gt=0, le=100)
    max_teams: Optional[int] = Field(None, gt=0)

    # Recurring-schedule template config (optional -- only set when this
    # row is itself a daily-generating schedule template).
    is_recurring_schedule: bool = False
    daily_slot_times: Optional[list[str]] = None
    category: Optional[ScheduleCategory] = None
    squad_size: int = Field(default=4, gt=0, le=100)

    @staticmethod
    def _validate_team_size(registration_mode: TeamRegistrationMode, team_size: int) -> None:
        if registration_mode == TeamRegistrationMode.SOLO and team_size != 1:
            raise ValueError("team_size must be 1 when registration_mode is 'solo'")
        if registration_mode != TeamRegistrationMode.SOLO and team_size < 2:
            raise ValueError(
                "team_size must be at least 2 for 'team_invite' or 'auto_random' modes"
            )

    @staticmethod
    def _validate_capacity(
        registration_mode: TeamRegistrationMode,
        team_size: int,
        max_players: int,
        max_teams: Optional[int],
    ) -> None:
        """For team-based tournaments, max_players is the total player-slot
        capacity, not the number of teams. Left unchecked, an organizer who
        sets max_players to (for example) the intended number of teams will
        find every team capped at 1 member as soon as the first team fills
        that slot -- so we enforce that max_players is always big enough to
        hold at least one full team, and exactly matches max_teams *
        team_size when both are given."""
        if registration_mode == TeamRegistrationMode.SOLO:
            return
        if max_players < team_size:
            raise ValueError(
                f"max_players ({max_players}) must be at least team_size "
                f"({team_size}) -- it counts total players across all teams, "
                f"not number of teams"
            )
        if max_players % team_size != 0:
            raise ValueError(
                f"max_players ({max_players}) must be a multiple of team_size "
                f"({team_size}) so every team slot can be filled"
            )
        if max_teams is not None and max_teams * team_size != max_players:
            raise ValueError(
                f"max_players ({max_players}) must equal max_teams * team_size "
                f"({max_teams} * {team_size} = {max_teams * team_size})"
            )

    def model_post_init(self, __context) -> None:
        self._validate_team_size(self.registration_mode, self.team_size)
        self._validate_capacity(
            self.registration_mode, self.team_size, self.max_players, self.max_teams
        )


class TournamentCustomCreate(BaseModel):
    """Payload for a regular (non-admin) user creating their own custom
    tournament from the app's "Custom Tournament" flow. Deliberately much
    smaller than TournamentCreate -- no admin-only fields (visibility,
    is_featured, recurring-schedule config, etc). Host sets only the entry
    fee and player count; prize_pool is always derived server-side as
    entry_fee * max_players * (1 - PLATFORM_COMMISSION_RATE), never trusted
    from the client.
    """

    title: str = Field(..., min_length=3, max_length=200)
    description: Optional[str] = Field(None, max_length=5000)
    rules: Optional[str] = Field(None, max_length=5000)
    game_id: UUID
    mode_id: Optional[UUID] = None
    map_id: Optional[UUID] = None
    entry_fee: Decimal = Field(..., gt=0, le=Decimal("100000"))
    max_players: int = Field(..., ge=2, le=1000)
    registration_mode: TeamRegistrationMode = TeamRegistrationMode.SOLO
    team_size: int = Field(default=1, gt=0, le=100)
    max_teams: Optional[int] = Field(None, gt=0)

    @staticmethod
    def _validate_team_size(registration_mode: TeamRegistrationMode, team_size: int) -> None:
        if registration_mode == TeamRegistrationMode.SOLO and team_size != 1:
            raise ValueError("team_size must be 1 when registration_mode is 'solo'")
        if registration_mode != TeamRegistrationMode.SOLO and team_size < 2:
            raise ValueError(
                "team_size must be at least 2 for 'team_invite' or 'auto_random' modes"
            )

    @staticmethod
    def _validate_capacity(
        registration_mode: TeamRegistrationMode,
        team_size: int,
        max_players: int,
        max_teams: Optional[int],
    ) -> None:
        if registration_mode == TeamRegistrationMode.SOLO:
            return
        if max_players < team_size:
            raise ValueError(
                f"max_players ({max_players}) must be at least team_size ({team_size})"
            )
        if max_players % team_size != 0:
            raise ValueError(
                f"max_players ({max_players}) must be a multiple of team_size ({team_size})"
            )
        if max_teams is not None and max_teams * team_size != max_players:
            raise ValueError(
                f"max_players ({max_players}) must equal max_teams * team_size"
            )

    def model_post_init(self, __context) -> None:
        self._validate_team_size(self.registration_mode, self.team_size)
        self._validate_capacity(
            self.registration_mode, self.team_size, self.max_players, self.max_teams
        )


class TournamentUpdate(BaseModel):
    title: Optional[str] = Field(None, min_length=3, max_length=200)
    description: Optional[str] = Field(None, max_length=5000)
    rules: Optional[str] = Field(None, max_length=5000)
    mode_id: Optional[UUID] = None
    map_id: Optional[UUID] = None
    organizer: Optional[str] = Field(None, min_length=2, max_length=150)
    entry_fee: Optional[Decimal] = Field(None, ge=0)
    prize_pool: Optional[Decimal] = Field(None, ge=0)
    max_players: Optional[int] = Field(None, gt=0, le=100000)
    visibility: Optional[TournamentVisibility] = None
    is_featured: Optional[bool] = None
    max_teams: Optional[int] = Field(None, gt=0)
    daily_slot_times: Optional[list[str]] = None
    # Prize type -- editable on an individual generated slot too (e.g.
    # admin bumps this one tournament's per-kill rate for a special
    # event), same override pattern as entry_fee/prize_pool.
    prize_type: Optional[PrizeType] = None
    rank_prize_rules: Optional[list[RankPrizeRule]] = None
    per_kill_amount: Optional[Decimal] = Field(None, ge=0)
    win_amount: Optional[Decimal] = Field(None, ge=0)
    # registration_mode and team_size are intentionally NOT editable here once
    # a tournament has any teams/participants attached -- see
    # TournamentService.update_tournament, which blocks changing them after
    # players have joined, to avoid corrupting existing teams.

    @model_validator(mode="after")
    def _check_prize_type_fields(self) -> "TournamentUpdate":
        if self.prize_type == PrizeType.RANK and not self.rank_prize_rules:
            raise ValueError("rank_prize_rules is required when setting prize_type='rank'")
        if self.prize_type == PrizeType.PER_KILL and self.per_kill_amount is None:
            raise ValueError("per_kill_amount is required when setting prize_type='per_kill'")
        if self.prize_type == PrizeType.WIN and self.win_amount is None:
            raise ValueError("win_amount is required when setting prize_type='win'")
        return self


class TournamentStatusUpdate(BaseModel):
    status: TournamentStatus


class TournamentPublishRoom(BaseModel):
    room_id: str = Field(..., min_length=1, max_length=100)
    room_password: str = Field(..., min_length=1, max_length=100)


class TournamentRoomRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    room_id: Optional[str] = None
    room_password: Optional[str] = None
    published_at: Optional[datetime] = None
    auto_complete_at: Optional[datetime] = None


class TournamentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    short_id: int
    tournament_uid: str
    title: str
    slug: str
    description: Optional[str] = None
    rules: Optional[str] = None
    game_id: UUID
    mode_id: Optional[UUID] = None
    map_id: Optional[UUID] = None
    banner_url: Optional[str] = None
    cover_url: Optional[str] = None
    organizer: str
    entry_fee: Decimal
    prize_pool: Decimal
    prize_type: PrizeType
    rank_prize_rules: Optional[list[RankPrizeRule]] = None
    per_kill_amount: Optional[Decimal] = None
    win_amount: Optional[Decimal] = None
    max_players: int
    current_players: int
    status: TournamentStatus
    visibility: TournamentVisibility
    is_featured: bool
    room_id: Optional[str] = None
    room_password: Optional[str] = None
    published_at: Optional[datetime] = None
    auto_complete_at: Optional[datetime] = None
    starts_at: Optional[datetime] = None
    registration_mode: TeamRegistrationMode
    team_size: int
    max_teams: Optional[int] = None
    is_recurring_schedule: bool
    category: Optional[ScheduleCategory] = None
    squad_size: int
    daily_slot_times: Optional[list[str]] = None
    created_by: Optional[UUID] = None
    created_at: datetime
    updated_at: datetime


class TournamentListItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tournament_uid: str
    title: str
    slug: str
    game_id: UUID
    banner_url: Optional[str] = None
    organizer: str
    entry_fee: Decimal
    prize_pool: Decimal
    prize_type: PrizeType
    per_kill_amount: Optional[Decimal] = None
    win_amount: Optional[Decimal] = None
    max_players: int
    current_players: int
    status: TournamentStatus
    visibility: TournamentVisibility
    is_featured: bool
    registration_mode: TeamRegistrationMode
    team_size: int
    starts_at: Optional[datetime] = None


class PaginatedTournaments(BaseModel):
    items: list[TournamentListItem]
    total: int
    page: int
    page_size: int
    total_pages: int


class TournamentAssetUploadResponse(BaseModel):
    url: str