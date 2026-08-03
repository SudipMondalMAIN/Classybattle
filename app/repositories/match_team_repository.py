"""
MatchTeam repository — queries for per-slot Clash-Squad-style teams.
"""
from typing import Optional, Sequence
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.match_team import MatchTeam, MatchTeamStatus
from app.repositories.base import BaseRepository


class MatchTeamRepository(BaseRepository[MatchTeam]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, MatchTeam)

    async def get_by_invite_code(self, invite_code: str) -> Optional[MatchTeam]:
        stmt = select(MatchTeam).where(
            MatchTeam.invite_code == invite_code.upper(),
            MatchTeam.deleted_at.is_(None),
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_for_match(self, match_id: UUID) -> Sequence[MatchTeam]:
        stmt = select(MatchTeam).where(
            MatchTeam.match_id == match_id, MatchTeam.deleted_at.is_(None)
        )
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def find_open_random_team(self, match_id: UUID) -> Optional[MatchTeam]:
        """A team on this match that was started via random matchmaking and
        still has an open slot — used to pair a new random-join user into
        an existing group before starting a fresh team."""
        stmt = select(MatchTeam).where(
            MatchTeam.match_id == match_id,
            MatchTeam.is_random.is_(True),
            MatchTeam.status == MatchTeamStatus.FORMING,
            MatchTeam.current_members < MatchTeam.team_size,
            MatchTeam.deleted_at.is_(None),
        )
        result = await self.session.execute(stmt)
        return result.scalars().first()

    async def count_teams_for_match(self, match_id: UUID) -> int:
        teams = await self.list_for_match(match_id)
        return len([t for t in teams if t.status != MatchTeamStatus.DISBANDED])
