"""
TournamentTeam repository — queries for per-slot Clash-Squad-style teams.
"""
from typing import Optional, Sequence
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.tournament_team import TournamentTeam, TournamentTeamStatus
from app.repositories.base import BaseRepository


class TournamentTeamRepository(BaseRepository[TournamentTeam]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, TournamentTeam)

    async def get_by_invite_code(self, invite_code: str) -> Optional[TournamentTeam]:
        stmt = select(TournamentTeam).where(
            TournamentTeam.invite_code == invite_code.upper(),
            TournamentTeam.deleted_at.is_(None),
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_for_tournament(self, tournament_id: UUID) -> Sequence[TournamentTeam]:
        stmt = select(TournamentTeam).where(
            TournamentTeam.tournament_id == tournament_id, TournamentTeam.deleted_at.is_(None)
        )
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def find_open_random_team(self, tournament_id: UUID) -> Optional[TournamentTeam]:
        """A team on this match that was started via random matchmaking and
        still has an open slot — used to pair a new random-join user into
        an existing group before starting a fresh team."""
        stmt = select(TournamentTeam).where(
            TournamentTeam.tournament_id == tournament_id,
            TournamentTeam.is_random.is_(True),
            TournamentTeam.status == TournamentTeamStatus.FORMING,
            TournamentTeam.current_members < TournamentTeam.team_size,
            TournamentTeam.deleted_at.is_(None),
        )
        result = await self.session.execute(stmt)
        return result.scalars().first()

    async def count_teams_for_match(self, tournament_id: UUID) -> int:
        teams = await self.list_for_tournament(tournament_id)
        return len([t for t in teams if t.status != TournamentTeamStatus.DISBANDED])
