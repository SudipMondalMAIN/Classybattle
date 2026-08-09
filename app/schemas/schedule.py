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

from app.models.tournament import ScheduleCategory

_TIME_RE = r"^([01]\d|2[0-3]):[0-5]\d$"


def _validate_times(v: list[str]) -> list[str]:
    import re

    if not v:
        raise ValueError("daily_slot_times cannot be empty — add at least one match time")
    for t in v:
        if not re.match(_TIME_RE, t):
            raise ValueError(f"Invalid time '{t}' — expected 24h 'HH:MM' format, e.g. '18:30'")
    return v


class ScheduleCreate(BaseModel):
    game_id: UUID
    category: ScheduleCategory
    squad_size: int = Field(default=4, gt=1, le=10, description="Only used when category='squad'")
    entry_fee: Decimal = Field(default=Decimal("0"), ge=0)
    prize_pool: Decimal = Field(default=Decimal("0"), ge=0)
    max_players_per_slot: int = Field(..., gt=0, le=1000)
    banner_url: Optional[str] = Field(default=None, description="Copied onto every generated slot's banner_url")
    cover_url: Optional[str] = Field(default=None, description="Copied onto every generated slot's cover_url")
    daily_slot_times: list[str] = Field(
        ..., description="One '24h HH:MM' string per match generated each day, e.g. ['10:00','10:30',...]. Count = matches/day (default 27, but any number works)."
    )

    @field_validator("daily_slot_times")
    @classmethod
    def _check_times(cls, v):
        return _validate_times(v)

    @model_validator(mode="after")
    def _check_squad_capacity(self) -> "ScheduleCreate":
        # category drives registration_mode downstream (SQUAD -> AUTO_RANDOM,
        # team_size=squad_size). Guard the capacity math here too so a SQUAD
        # schedule can never be created with a max_players_per_slot that
        # doesn't divide evenly into full squads.
        if self.category == ScheduleCategory.SQUAD:
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

    @field_validator("daily_slot_times")
    @classmethod
    def _check_times(cls, v):
        if v is None:
            return v
        return _validate_times(v)


class ScheduleRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    game_id: UUID
    category: ScheduleCategory
    squad_size: int
    entry_fee: Decimal
    prize_pool: Decimal
    max_players: int
    banner_url: Optional[str] = None
    cover_url: Optional[str] = None
    daily_slot_times: Optional[list[str]] = None
    matches_per_day: int = 0
    last_generated_on: Optional[datetime] = None

    @model_validator(mode="after")
    def _compute_matches_per_day(self) -> "ScheduleRead":
        self.matches_per_day = len(self.daily_slot_times or [])
        return self


class GenerateSlotsRequest(BaseModel):
    target_date: Optional[datetime] = Field(
        default=None, description="Date to generate slots for (defaults to today, UTC)"
    )