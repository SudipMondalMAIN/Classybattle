"""
Public Result schemas — for result.classybattle.online.

Patch notes: new file app/schemas/public_result.py.
Deliberately exposes only name + per-game UID + placement + prize amount —
never email, phone, wallet balance, or payment details.
"""
from datetime import datetime
from decimal import Decimal
from typing import Optional
from uuid import UUID

from pydantic import BaseModel


def _extract_game_uid(game_profile) -> Optional[str]:
    """UserGameProfile.data is a free-form JSONB dict validated against the
    game's own profile_schema, so the UID key isn't fixed column — most
    games use "uid", some may use "player_id" etc. Check common keys."""
    if not game_profile or not game_profile.data:
        return None
    data = game_profile.data
    for key in ("uid", "player_id", "game_uid", "id"):
        if data.get(key):
            return str(data[key])
    return None


class PublicPlayerEntry(BaseModel):
    name: str
    game_uid: Optional[str] = None
    kills: Optional[int] = None
    is_winner: bool = False
    rank: Optional[int] = None
    winning_amount: Optional[Decimal] = None


class PublicResultSummary(BaseModel):
    tournament_id: UUID
    tournament_uid: str
    title: str
    starts_at: datetime
    prize_pool: Decimal
    participant_count: int
    approved_at: Optional[datetime] = None


class PublicResultDetail(BaseModel):
    tournament_id: UUID
    tournament_uid: str
    title: str
    starts_at: datetime
    prize_pool: Decimal
    winners: list[PublicPlayerEntry]
    participants: list[PublicPlayerEntry]

    @classmethod
    def build(cls, tournament, winners, participants) -> "PublicResultDetail":
        winner_entries = []
        for w in winners:
            kills = None
            winning_amount = None
            if w.participant is not None:
                name = w.participant.user.full_name if getattr(w.participant, "user", None) else "Player"
                uid = _extract_game_uid(getattr(w.participant, "game_profile", None))
                # kills/winning_amount live on TournamentParticipant, not on
                # TournamentWinner itself — pull them across so the winner
                # card can show eliminations + reward, same as the
                # participants list does.
                kills = getattr(w.participant, "kills", None)
                winning_amount = getattr(w.participant, "winning_amount", None)
            elif w.team is not None:
                name = w.team.team_name
                uid = None
            else:
                continue
            winner_entries.append(
                PublicPlayerEntry(
                    name=name,
                    game_uid=uid,
                    kills=kills,
                    is_winner=True,
                    rank=w.rank,
                    winning_amount=winning_amount,
                )
            )

        participant_entries = []
        for p in participants:
            if p.participant is not None:
                name = p.participant.user.full_name if getattr(p.participant, "user", None) else "Player"
                uid = _extract_game_uid(getattr(p.participant, "game_profile", None))
            elif p.team is not None:
                name = p.team.team_name
                uid = None
            else:
                continue
            participant_entries.append(
                PublicPlayerEntry(
                    name=name,
                    game_uid=uid,
                    kills=p.kills,
                    is_winner=p.is_winner,
                    rank=p.rank,
                    winning_amount=p.winning_amount,
                )
            )

        return cls(
            tournament_id=tournament.id,
            tournament_uid=tournament.tournament_uid,
            title=tournament.title,
            starts_at=tournament.starts_at,
            prize_pool=tournament.prize_pool,
            winners=winner_entries,
            participants=participant_entries,
        )