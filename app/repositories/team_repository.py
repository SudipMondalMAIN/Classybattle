"""
Team repository — queries specific to the Team System (Phase 6).
"""
from typing import Optional, Sequence
from uuid import UUID

from sqlalchemy import String, asc, cast, desc, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.team import Team, TeamStatus
from app.repositories.base import BaseRepository

_SORTABLE_FIELDS = {
    "created_at": Team.created_at,
    "team_name": Team.team_name,
    "current_members": Team.current_members,
    "status": Team.status,
}


class TeamRepository(BaseRepository[Team]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, Team)

    async def get_by_invite_code(
        self, invite_code: str, include_deleted: bool = False
    ) -> Optional[Team]:
        stmt = select(Team).where(Team.invite_code == invite_code)
        if not include_deleted:
            stmt = stmt.where(Team.deleted_at.is_(None))
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def invite_code_exists(self, invite_code: str) -> bool:
        stmt = select(Team.id).where(Team.invite_code == invite_code)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none() is not None

    async def name_exists_in_tournament(
        self, tournament_id: UUID, team_name: str, exclude_team_id: Optional[UUID] = None
    ) -> bool:
        stmt = select(Team.id).where(
            Team.tournament_id == tournament_id,
            Team.deleted_at.is_(None),
            func.lower(Team.team_name) == team_name.strip().lower(),
        )
        if exclude_team_id is not None:
            stmt = stmt.where(Team.id != exclude_team_id)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none() is not None

    async def count_active_for_tournament(self, tournament_id: UUID) -> int:
        stmt = select(func.count(Team.id)).where(
            Team.tournament_id == tournament_id,
            Team.deleted_at.is_(None),
            Team.status != TeamStatus.DISBANDED,
        )
        result = await self.session.execute(stmt)
        return result.scalar_one()

    async def list_for_tournament(
        self,
        tournament_id: UUID,
        *,
        page: int = 1,
        page_size: int = 20,
        status: Optional[TeamStatus] = None,
        search: Optional[str] = None,
        sort_by: str = "created_at",
        sort_order: str = "desc",
        include_deleted: bool = False,
    ) -> tuple[Sequence[Team], int]:
        conditions = [Team.tournament_id == tournament_id]
        if not include_deleted:
            conditions.append(Team.deleted_at.is_(None))
        if status is not None:
            conditions.append(Team.status == status)
        if search:
            like = f"%{search.strip().lower()}%"
            conditions.append(
                or_(
                    func.lower(cast(Team.team_name, String)).like(like),
                    func.lower(cast(Team.team_uid, String)).like(like),
                )
            )

        count_stmt = select(func.count(Team.id)).where(*conditions)
        total = (await self.session.execute(count_stmt)).scalar_one()

        sort_column = _SORTABLE_FIELDS.get(sort_by, Team.created_at)
        order_fn = asc if sort_order.lower() == "asc" else desc

        stmt = (
            select(Team)
            .where(*conditions)
            .order_by(order_fn(sort_column))
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        result = await self.session.execute(stmt)
        return result.scalars().all(), total

    async def list_all_active_for_tournament(self, tournament_id: UUID) -> Sequence[Team]:
        """Non-paginated fetch used by organizer bulk operations (e.g. auto assignment)."""
        stmt = select(Team).where(
            Team.tournament_id == tournament_id,
            Team.deleted_at.is_(None),
            Team.status != TeamStatus.DISBANDED,
        )
        result = await self.session.execute(stmt)
        return result.scalars().all()
