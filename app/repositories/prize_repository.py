"""
Prize Pool / Prize Payout repositories — Phase 10.
"""
from typing import Optional, Sequence
from uuid import UUID

from sqlalchemy import asc, desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.prize import PrizePayout, PrizePayoutStatus, PrizePool, PrizePoolStatus
from app.repositories.base import BaseRepository

_PAYOUT_SORTABLE_FIELDS = {
    "created_at": PrizePayout.created_at,
    "rank": PrizePayout.rank,
    "amount": PrizePayout.amount,
    "status": PrizePayout.status,
    "paid_at": PrizePayout.paid_at,
}


class PrizePoolRepository(BaseRepository[PrizePool]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, PrizePool)

    async def get_by_tournament_id(self, tournament_id: UUID) -> Optional[PrizePool]:
        stmt = select(PrizePool).where(
            PrizePool.tournament_id == tournament_id, PrizePool.deleted_at.is_(None)
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_id_for_update(self, id_: UUID) -> Optional[PrizePool]:
        stmt = select(PrizePool).where(PrizePool.id == id_, PrizePool.deleted_at.is_(None))
        if self.session.bind.dialect.name != "sqlite":
            stmt = stmt.with_for_update()
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_paginated(
        self,
        *,
        page: int = 1,
        page_size: int = 20,
        status: Optional[PrizePoolStatus] = None,
        sort_by: str = "created_at",
        sort_order: str = "desc",
    ) -> tuple[Sequence[PrizePool], int]:
        conditions = [PrizePool.deleted_at.is_(None)]
        if status is not None:
            conditions.append(PrizePool.status == status)

        count_stmt = select(func.count(PrizePool.id)).where(*conditions)
        total = (await self.session.execute(count_stmt)).scalar_one()

        sort_column = {"created_at": PrizePool.created_at, "total_amount": PrizePool.total_amount}.get(
            sort_by, PrizePool.created_at
        )
        order_fn = asc if sort_order.lower() == "asc" else desc

        stmt = (
            select(PrizePool)
            .where(*conditions)
            .order_by(order_fn(sort_column))
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        result = await self.session.execute(stmt)
        return result.scalars().all(), total


class PrizePayoutRepository(BaseRepository[PrizePayout]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, PrizePayout)

    async def get_by_pool_and_rank(self, prize_pool_id: UUID, rank: int) -> Optional[PrizePayout]:
        stmt = select(PrizePayout).where(
            PrizePayout.prize_pool_id == prize_pool_id,
            PrizePayout.rank == rank,
            PrizePayout.deleted_at.is_(None),
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_pool_and_participant(
        self, prize_pool_id: UUID, participant_id: UUID
    ) -> Optional[PrizePayout]:
        stmt = select(PrizePayout).where(
            PrizePayout.prize_pool_id == prize_pool_id,
            PrizePayout.participant_id == participant_id,
            PrizePayout.deleted_at.is_(None),
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_id_for_update(self, id_: UUID) -> Optional[PrizePayout]:
        stmt = select(PrizePayout).where(PrizePayout.id == id_, PrizePayout.deleted_at.is_(None))
        if self.session.bind.dialect.name != "sqlite":
            stmt = stmt.with_for_update()
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_for_pool(self, prize_pool_id: UUID) -> Sequence[PrizePayout]:
        stmt = (
            select(PrizePayout)
            .where(PrizePayout.prize_pool_id == prize_pool_id, PrizePayout.deleted_at.is_(None))
            .order_by(PrizePayout.rank.asc())
        )
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def list_pending_or_failed_for_pool(self, prize_pool_id: UUID) -> Sequence[PrizePayout]:
        stmt = (
            select(PrizePayout)
            .where(
                PrizePayout.prize_pool_id == prize_pool_id,
                PrizePayout.deleted_at.is_(None),
                PrizePayout.status.in_(
                    [PrizePayoutStatus.PENDING, PrizePayoutStatus.FAILED]
                ),
            )
            .order_by(PrizePayout.rank.asc())
        )
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def list_paginated(
        self,
        *,
        page: int = 1,
        page_size: int = 20,
        prize_pool_id: Optional[UUID] = None,
        tournament_id: Optional[UUID] = None,
        user_id: Optional[UUID] = None,
        status: Optional[PrizePayoutStatus] = None,
        sort_by: str = "created_at",
        sort_order: str = "desc",
    ) -> tuple[Sequence[PrizePayout], int]:
        conditions = [PrizePayout.deleted_at.is_(None)]
        if prize_pool_id is not None:
            conditions.append(PrizePayout.prize_pool_id == prize_pool_id)
        if tournament_id is not None:
            conditions.append(PrizePayout.tournament_id == tournament_id)
        if user_id is not None:
            conditions.append(PrizePayout.user_id == user_id)
        if status is not None:
            conditions.append(PrizePayout.status == status)

        count_stmt = select(func.count(PrizePayout.id)).where(*conditions)
        total = (await self.session.execute(count_stmt)).scalar_one()

        sort_column = _PAYOUT_SORTABLE_FIELDS.get(sort_by, PrizePayout.created_at)
        order_fn = asc if sort_order.lower() == "asc" else desc

        stmt = (
            select(PrizePayout)
            .where(*conditions)
            .order_by(order_fn(sort_column))
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        result = await self.session.execute(stmt)
        return result.scalars().all(), total
