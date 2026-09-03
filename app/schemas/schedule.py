"""
Schedule (daily match config) Pydantic schemas — the simplified flow:
Admin picks a Game + category (SOLO or SQUAD) and a list of match times
for the day. No tournament creation, no map/mode picking.
"""
from datetime import datetime
from decimal import Decimal
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.models.tournament import PrizeType, ScheduleCategory

_TIME_RE = r"^([01]\d|2[0-3]):[0-5]\d$"


def _validate_times(v: list[str]) -> list[str]:
    import re

    if not v:
        raise ValueError("daily_slot_times cannot be empty — add at least one match time")
    for t in v:
        if not re.match(_TIME_RE, t):
            raise ValueError(f"Invalid time '{t}' — expected 24h 'HH:MM' format, e.g. '18:30'")
    return v


class RankPrizeRule(BaseModel):
    rank: int = Field(..., gt=0)
    amount: Decimal = Field(..., ge=0)


def _validate_rank_prize_rules(v: Optional[list[RankPrizeRule]]) -> Optional[list[RankPrizeRule]]:
    if v is None:
        return v
    if not v:
        raise ValueError("rank_prize_rules cannot be empty when provided")
    ranks = [r.rank for r in v]
    if len(ranks) != len(set(ranks)):
        raise ValueError("rank_prize_rules contains duplicate ranks")
    return v


class ScheduleCreate(BaseModel):
    game_id: UUID
    category: ScheduleCategory
    squad_size: int = Field(
        default=4, gt=1, le=10,
        description="Only used when category='squad' or 'duo'. Ignored for 'solo'; forced to 2 for 'duo'.",
    )
    entry_fee: Decimal = Field(default=Decimal("0"), ge=0)
    prize_pool: Decimal = Field(default=Decimal("0"), ge=0)
    max_players_per_slot: int = Field(..., gt=0, le=1000)
    banner_url: Optional[str] = Field(default=None, description="Copied onto every generated slot's banner_url")
    cover_url: Optional[str] = Field(default=None, description="Copied onto every generated slot's cover_url")
    daily_slot_times: list[str] = Field(
        ..., description="One '24h HH:MM' string per match generated each day, e.g. ['10:00','10:30',...]. Count = matches/day (default 27, but any number works)."
    )

    # ---------------------------------------------------------------
    # Prize type -- Admin picks one at schedule-creation time, editable
    # afterwards via ScheduleUpdate (same as entry_fee/prize_pool).
    # ---------------------------------------------------------------
    prize_type: PrizeType = Field(
        default=PrizeType.RANK,
        description="How winners get paid: rank | per_kill | win.",
    )
    rank_prize_rules: Optional[list[RankPrizeRule]] = Field(
        default=None,
        description="Required when prize_type='rank'. e.g. [{'rank':1,'amount':500},{'rank':2,'amount':300}]",
    )
    per_kill_amount: Optional[Decimal] = Field(
        default=None, ge=0, description="Required when prize_type='per_kill'. ₹ per confirmed kill."
    )
    win_amount: Optional[Decimal] = Field(
        default=None, ge=0, description="Required when prize_type='win'. Flat ₹ for the declared winner."
    )

    @field_validator("daily_slot_times")
    @classmethod
    def _check_times(cls, v):
        return _validate_times(v)

    @field_validator("rank_prize_rules")
    @classmethod
    def _check_rank_rules(cls, v):
        return _validate_rank_prize_rules(v)

    @model_validator(mode="after")
    def _check_prize_type_fields(self) -> "ScheduleCreate":
        if self.prize_type == PrizeType.RANK and not self.rank_prize_rules:
            raise ValueError("rank_prize_rules is required when prize_type='rank'")
        if self.prize_type == PrizeType.PER_KILL and self.per_kill_amount is None:
            raise ValueError("per_kill_amount is required when prize_type='per_kill'")
        if self.prize_type == PrizeType.WIN and self.win_amount is None:
            raise ValueError("win_amount is required when prize_type='win'")
        return self

    @model_validator(mode="after")
    def _check_squad_capacity(self) -> "ScheduleCreate":
        # category drives registration_mode downstream (SQUAD/DUO ->
        # AUTO_RANDOM, team_size=squad_size). Guard the capacity math here
        # too so a SQUAD/DUO schedule can never be created with a
        # max_players_per_slot that doesn't divide evenly into full teams.
        if self.category == ScheduleCategory.DUO:
            # Duo is always a fixed 2-player team -- lock it regardless of
            # whatever squad_size was passed in.
            self.squad_size = 2
        if self.category in (ScheduleCategory.SQUAD, ScheduleCategory.DUO):
            if self.max_players_per_slot < self.squad_size:
                raise ValueError(
                    f"max_players_per_slot ({self.max_players_per_slot}) must be at least "
                    f"squad_size ({self.squad_size})"
                )
            if self.max_players_per_slot % self.squad_size != 0:
                raise ValueError(
                    f"max_players_per_slot ({self.max_players_per_slot}) must be a multiple "
                    f"of squad_size ({self.squad_size}) so every squad slot can be filled"
                )
        return self


class ScheduleUpdate(BaseModel):
    rules: Optional[str] = Field(
        None, max_length=5000,
        description="Overrides the auto-generated rules text. Applied to every future generated slot.",
    )
    entry_fee: Optional[Decimal] = Field(None, ge=0)
    prize_pool: Optional[Decimal] = Field(None, ge=0)
    max_players: Optional[int] = Field(None, gt=0, le=1000)
    squad_size: Optional[int] = Field(None, gt=1, le=10)
    banner_url: Optional[str] = Field(default=None, description="Copied onto every future generated slot's banner_url")
    cover_url: Optional[str] = Field(default=None, description="Copied onto every future generated slot's cover_url")
    daily_slot_times: Optional[list[str]] = Field(
        None, description="Replaces the full list — admin can add/remove/edit match times/count here (e.g. 27 -> 28)."
    )
    is_active: Optional[bool] = None

    # Prize type -- editable any time, same as entry_fee/prize_pool.
    # Passing prize_type alone (without the matching amount field) is
    # rejected, so a schedule can never end up in a state where
    # prize_type='per_kill' but per_kill_amount is still null.
    prize_type: Optional[PrizeType] = None
    rank_prize_rules: Optional[list[RankPrizeRule]] = None
    per_kill_amount: Optional[Decimal] = Field(None, ge=0)
    win_amount: Optional[Decimal] = Field(None, ge=0)

    @field_validator("daily_slot_times")
    @classmethod
    def _check_times(cls, v):
        if v is None:
            return v
        return _validate_times(v)

    @field_validator("rank_prize_rules")
    @classmethod
    def _check_rank_rules(cls, v):
        return _validate_rank_prize_rules(v)

    @model_validator(mode="after")
    def _check_prize_type_fields(self) -> "ScheduleUpdate":
        if self.prize_type == PrizeType.RANK and not self.rank_prize_rules:
            raise ValueError("rank_prize_rules is required when setting prize_type='rank'")
        if self.prize_type == PrizeType.PER_KILL and self.per_kill_amount is None:
            raise ValueError("per_kill_amount is required when setting prize_type='per_kill'")
        if self.prize_type == PrizeType.WIN and self.win_amount is None:
            raise ValueError("win_amount is required when setting prize_type='win'")
        return self


class ScheduleRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    game_id: UUID
    category: ScheduleCategory
    rules: Optional[str] = None
    squad_size: int
    entry_fee: Decimal
    prize_pool: Decimal
    max_players: int
    banner_url: Optional[str] = None
    cover_url: Optional[str] = None
    daily_slot_times: Optional[list[str]] = None
    matches_per_day: int = 0
    last_generated_on: Optional[datetime] = None
    prize_type: PrizeType = PrizeType.RANK
    rank_prize_rules: Optional[list[RankPrizeRule]] = None
    per_kill_amount: Optional[Decimal] = None
    win_amount: Optional[Decimal] = None

    @model_validator(mode="after")
    def _compute_matches_per_day(self) -> "ScheduleRead":
        self.matches_per_day = len(self.daily_slot_times or [])
        return self


class GenerateSlotsRequest(BaseModel):
    target_date: Optional[datetime] = Field(
        default=None, description="Date to generate slots for (defaults to today, UTC)"
    )