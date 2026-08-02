"""
Participant repository — queries specific to Tournament Registration (Phase 5).
"""
from typing import Optional, Sequence
from uuid import UUID

from sqlalchemy import String, asc, cast, desc, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.models.participant import Participant, ParticipantStatus
from app.repositories.base import BaseRepository

_SORTABLE_FIELDS = {
    "created_at": Participant.created_at,
    "joined_at": Participant.joined_at,
    "checked_in_at": Participant.checked_in_at,
    "status": Participant.status,
    "team_name": Participant.team_name,
}


class ParticipantRepository(BaseRepository[Participant]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, Participant)

    async def get_by_tournament_and_user(
        self, tournament_id: UUID, user_id: UUID, include_deleted: bool = False
    ) -> Optional[Participant]:
        stmt = select(Participant).where(
            Participant.tournament_id == tournament_id,
            Participant.user_id == user_id,
        )
        if not include_deleted:
            stmt = stmt.where(Participant.deleted_at.is_(None))
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def count_active_for_tournament(self, tournament_id: UUID) -> int:
        """Counts participants that occupy a capacity slot (pending/confirmed/checked_in)."""
        stmt = select(func.count(Participant.id)).where(
            Participant.tournament_id == tournament_id,
            Participant.deleted_at.is_(None),
            Participant.status.in_(
                [
                    ParticipantStatus.PENDING,
                    ParticipantStatus.CONFIRMED,
                    ParticipantStatus.CHECKED_IN,
                ]
            ),
        )
        result = await self.session.execute(stmt)
        return result.scalar_one()

    async def list_for_tournament(
        self,
        tournament_id: UUID,
        *,
        page: int = 1,
        page_size: int = 20,
        status: Optional[ParticipantStatus] = None,
        search: Optional[str] = None,
        sort_by: str = "created_at",
        sort_order: str = "desc",
        include_deleted: bool = False,
    ) -> tuple[Sequence[Participant], int]:
        conditions = [Participant.tournament_id == tournament_id]
        if not include_deleted:
            conditions.append(Participant.deleted_at.is_(None))
        if status is not None:
            conditions.append(Participant.status == status)
        if search:
            like = f"%{search.strip().lower()}%"
            conditions.append(
                or_(
                    func.lower(cast(Participant.team_name, String)).like(like),
                    func.lower(cast(Participant.participant_uid, String)).like(like),
                )
            )

        count_stmt = select(func.count(Participant.id)).where(*conditions)
        total = (await self.session.execute(count_stmt)).scalar_one()

        sort_column = _SORTABLE_FIELDS.get(sort_by, Participant.created_at)
        order_fn = asc if sort_order.lower() == "asc" else desc

        stmt = (
            select(Participant)
            .where(*conditions)
            .order_by(order_fn(sort_column))
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        result = await self.session.execute(stmt)
        return result.scalars().all(), total

    async def list_active_for_tournament_all(
        self, tournament_id: UUID
    ) -> Sequence[Participant]:
        """Returns every capacity-occupying participant for a tournament,
        unpaginated. Used for bulk operations (e.g. refunding everyone when
        a tournament is cancelled) where we must touch every row, not just
        one page of them."""
        stmt = select(Participant).where(
            Participant.tournament_id == tournament_id,
            Participant.deleted_at.is_(None),
            Participant.status.in_(
                [
                    ParticipantStatus.PENDING,
                    ParticipantStatus.CONFIRMED,
                    ParticipantStatus.CHECKED_IN,
                ]
            ),
        )
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def list_for_user(
        self,
        user_id: UUID,
        *,
        page: int = 1,
        page_size: int = 20,
        status: Optional[ParticipantStatus] = None,
        sort_by: str = "created_at",
        sort_order: str = "desc",
        include_deleted: bool = False,
    ) -> tuple[Sequence[Participant], int]:
        conditions = [Participant.user_id == user_id]
        if not include_deleted:
            conditions.append(Participant.deleted_at.is_(None))
        if status is not None:
            conditions.append(Participant.status == status)

        count_stmt = select(func.count(Participant.id)).where(*conditions)
        total = (await self.session.execute(count_stmt)).scalar_one()

        sort_column = _SORTABLE_FIELDS.get(sort_by, Participant.created_at)
        order_fn = asc if sort_order.lower() == "asc" else desc

        stmt = (
            select(Participant)
            .where(*conditions)
            .order_by(order_fn(sort_column))
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        result = await self.session.execute(stmt)
        return result.scalars().all(), total

    async def list_shared_tournaments(self, user_id_a: UUID, user_id_b: UUID):
        """
        Returns (participant_a, participant_b) pairs for every tournament
        both users registered for — used by admins to verify whether a
        reporter and a reported player actually played together before
        acting on a report.
        """
        pa = aliased(Participant)
        pb = aliased(Participant)
        stmt = (
            select(pa, pb)
            .join(pb, pb.tournament_id == pa.tournament_id)
            .where(
                pa.user_id == user_id_a,
                pb.user_id == user_id_b,
                pa.deleted_at.is_(None),
                pb.deleted_at.is_(None),
            )
        )
        result = await self.session.execute(stmt)
        return result.all()
