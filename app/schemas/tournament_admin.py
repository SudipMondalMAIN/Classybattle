"""
Tournament Admin schemas -- powers the admin "tournament details" page:
who joined, kills, winner declaration, and winning-amount payout.
"""
from datetime import datetime
from decimal import Decimal
from typing import Optional
from uuid import UUID

from pydantic import BaseModel


class MatchAdminPlayerRead(BaseModel):
    user_id: UUID
    full_name: Optional[str] = None
    phone_number: Optional[str] = None
    game_nickname: Optional[str] = None
    game_uid: Optional[str] = None
    team_name: Optional[str] = None
    team_id: Optional[UUID] = None
    kills: int = 0
    is_winner: bool = False
    rank: Optional[int] = None
    winning_amount: Optional[Decimal] = None
    winning_paid_at: Optional[datetime] = None
    joined_at: Optional[datetime] = None


class MatchAdminDetailRead(BaseModel):
    id: UUID
    short_id: int
    match_uid: str
    game_id: UUID
    game_name: str
    category: Optional[str] = None
    team_format: Optional[str] = None
    scheduled_start: Optional[datetime] = None
    match_status: str
    room_id: Optional[str] = None
    room_password: Optional[str] = None
    entry_fee: Decimal
    prize_pool: Decimal
    total_joined: int
    max_players: int
    players: list[MatchAdminPlayerRead]


class DeclareResultRequest(BaseModel):
    kills: Optional[int] = None
    is_winner: Optional[bool] = None
    rank: Optional[int] = None


class PayWinnerRequest(BaseModel):
    amount: Decimal
    note: Optional[str] = None
