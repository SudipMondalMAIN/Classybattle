"""
TeamMember repository — queries specific to the Team System (Phase 6).
"""
from typing import Optional, Sequence
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.team_member import TeamMember
from app.repositories.base import BaseRepository


class TeamMemberRepository(BaseRepository[TeamMember]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, TeamMember)

    async def get_by_team_and_user(
        self, team_id: UUID, user_id: UUID
    ) -> Optional[TeamMember]:
        stmt = select(TeamMember).where(
            TeamMember.team_id == team_id,
            TeamMember.user_id == user_id,
            TeamMember.deleted_at.is_(None),
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_for_user_in_tournament(
        self, tournament_id: UUID, user_id: UUID
    ) -> Optional[TeamMember]:
        """Finds the membership (if any) a user already has among the teams
        belonging to a given tournament."""
        from app.models.team import Team  # local import avoids a circular import

        stmt = (
            select(TeamMember)
            .join(Team, Team.id == TeamMember.team_id)
            .where(
                Team.tournament_id == tournament_id,
                Team.deleted_at.is_(None),
                TeamMember.user_id == user_id,
                TeamMember.deleted_at.is_(None),
            )
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_for_team(self, team_id: UUID) -> Sequence[TeamMember]:
        stmt = select(TeamMember).where(
            TeamMember.team_id == team_id,
            TeamMember.deleted_at.is_(None),
        )
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def count_for_team(self, team_id: UUID) -> int:
        from sqlalchemy import func

        stmt = select(func.count(TeamMember.id)).where(
            TeamMember.team_id == team_id,
            TeamMember.deleted_at.is_(None),
        )
        result = await self.session.execute(stmt)
        return result.scalar_one()
