"""
MatchParticipant repository — queries for match team assignment, check-in
and no-show handling (Phase 7).
"""
from typing import Optional, Sequence
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.match_participant import MatchCheckInStatus, MatchParticipant
from app.repositories.base import BaseRepository


class MatchParticipantRepository(BaseRepository[MatchParticipant]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, MatchParticipant)

    async def list_for_match(self, match_id: UUID) -> Sequence[MatchParticipant]:
        stmt = (
            select(MatchParticipant)
            .where(
                MatchParticipant.match_id == match_id,
                MatchParticipant.deleted_at.is_(None),
            )
            .order_by(MatchParticipant.slot_number.asc())
        )
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def get_by_match_and_team(
        self, match_id: UUID, team_id: UUID
    ) -> Optional[MatchParticipant]:
        stmt = select(MatchParticipant).where(
            MatchParticipant.match_id == match_id,
            MatchParticipant.team_id == team_id,
            MatchParticipant.deleted_at.is_(None),
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_match_and_participant(
        self, match_id: UUID, participant_id: UUID
    ) -> Optional[MatchParticipant]:
        stmt = select(MatchParticipant).where(
            MatchParticipant.match_id == match_id,
            MatchParticipant.participant_id == participant_id,
            MatchParticipant.deleted_at.is_(None),
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def count_for_match(self, match_id: UUID) -> int:
        stmt = select(func.count(MatchParticipant.id)).where(
            MatchParticipant.match_id == match_id,
            MatchParticipant.deleted_at.is_(None),
        )
        result = await self.session.execute(stmt)
        return result.scalar_one()

    async def next_slot_number(self, match_id: UUID) -> int:
        stmt = select(func.max(MatchParticipant.slot_number)).where(
            MatchParticipant.match_id == match_id,
            MatchParticipant.deleted_at.is_(None),
        )
        result = await self.session.execute(stmt)
        current_max = result.scalar_one()
        return (current_max or 0) + 1

    async def count_by_checkin_status(
        self, match_id: UUID, status: MatchCheckInStatus
    ) -> int:
        stmt = select(func.count(MatchParticipant.id)).where(
            MatchParticipant.match_id == match_id,
            MatchParticipant.deleted_at.is_(None),
            MatchParticipant.check_in_status == status,
        )
        result = await self.session.execute(stmt)
        return result.scalar_one()
