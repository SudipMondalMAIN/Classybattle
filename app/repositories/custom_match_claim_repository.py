"""
Repository for CustomMatchClaim -- self-declared win/loss on 1v1 Custom
Tournaments.
"""
from typing import Optional, Sequence
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.custom_match_claim import CustomMatchClaim, CustomMatchClaimStatus
from app.repositories.base import BaseRepository


class CustomMatchClaimRepository(BaseRepository[CustomMatchClaim]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, CustomMatchClaim)

    async def get_by_tournament_and_user(
        self, tournament_id: UUID, user_id: UUID
    ) -> Optional[CustomMatchClaim]:
        stmt = select(CustomMatchClaim).where(
            CustomMatchClaim.tournament_id == tournament_id,
            CustomMatchClaim.user_id == user_id,
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_for_tournament(self, tournament_id: UUID) -> Sequence[CustomMatchClaim]:
        stmt = select(CustomMatchClaim).where(
            CustomMatchClaim.tournament_id == tournament_id
        )
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def list_pending(self, *, page: int = 1, page_size: int = 20) -> tuple[Sequence[CustomMatchClaim], int]:
        from sqlalchemy import func

        conditions = [CustomMatchClaim.status == CustomMatchClaimStatus.PENDING_REVIEW]
        count_stmt = select(func.count(CustomMatchClaim.id)).where(*conditions)
        total = (await self.session.execute(count_stmt)).scalar_one()

        stmt = (
            select(CustomMatchClaim)
            .where(*conditions)
            .order_by(CustomMatchClaim.submitted_at.asc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        result = await self.session.execute(stmt)
        return result.scalars().all(), total
