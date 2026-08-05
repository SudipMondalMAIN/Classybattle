"""
TournamentParticipant repository — queries for tournament team assignment, check-in
and no-show handling (Phase 7).
"""
from typing import Optional, Sequence
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.tournament_participant import TournamentCheckInStatus, TournamentParticipant
from app.repositories.base import BaseRepository


class TournamentParticipantRepository(BaseRepository[TournamentParticipant]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, TournamentParticipant)

    async def list_for_tournament(self, tournament_id: UUID) -> Sequence[TournamentParticipant]:
        stmt = (
            select(TournamentParticipant)
            .where(
                TournamentParticipant.tournament_id == tournament_id,
                TournamentParticipant.deleted_at.is_(None),
            )
            .order_by(TournamentParticipant.slot_number.asc())
        )
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def get_by_match_and_team(
        self, tournament_id: UUID, team_id: UUID
    ) -> Optional[TournamentParticipant]:
        stmt = select(TournamentParticipant).where(
            TournamentParticipant.tournament_id == tournament_id,
            TournamentParticipant.team_id == team_id,
            TournamentParticipant.deleted_at.is_(None),
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_match_and_participant(
        self, tournament_id: UUID, participant_id: UUID
    ) -> Optional[TournamentParticipant]:
        stmt = select(TournamentParticipant).where(
            TournamentParticipant.tournament_id == tournament_id,
            TournamentParticipant.participant_id == participant_id,
            TournamentParticipant.deleted_at.is_(None),
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def count_for_match(self, tournament_id: UUID) -> int:
        stmt = select(func.count(TournamentParticipant.id)).where(
            TournamentParticipant.tournament_id == tournament_id,
            TournamentParticipant.deleted_at.is_(None),
        )
        result = await self.session.execute(stmt)
        return result.scalar_one()

    async def next_slot_number(self, tournament_id: UUID) -> int:
        stmt = select(func.max(TournamentParticipant.slot_number)).where(
            TournamentParticipant.tournament_id == tournament_id,
            TournamentParticipant.deleted_at.is_(None),
        )
        result = await self.session.execute(stmt)
        current_max = result.scalar_one()
        return (current_max or 0) + 1

    async def count_by_checkin_status(
        self, tournament_id: UUID, status: TournamentCheckInStatus
    ) -> int:
        stmt = select(func.count(TournamentParticipant.id)).where(
            TournamentParticipant.tournament_id == tournament_id,
            TournamentParticipant.deleted_at.is_(None),
            TournamentParticipant.check_in_status == status,
        )
        result = await self.session.execute(stmt)
        return result.scalar_one()
