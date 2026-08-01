"""
Repository layer for the Team Community System — Phase 15B.
"""
from __future__ import annotations

from typing import Optional, Sequence
from uuid import UUID

from sqlalchemy import asc, desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.team_community import (
    TeamActivityFeedEntry,
    TeamActivityType,
    TeamAnnouncement,
    TeamInvitation,
    TeamInvitationStatus,
    TeamJoinRequest,
    TeamJoinRequestStatus,
)
from app.repositories.base import BaseRepository


class TeamInvitationRepository(BaseRepository[TeamInvitation]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, TeamInvitation)

    async def get_by_team_and_invitee(
        self, team_id: UUID, invitee_id: UUID, *, include_deleted: bool = False
    ) -> Optional[TeamInvitation]:
        stmt = select(TeamInvitation).where(
            TeamInvitation.team_id == team_id, TeamInvitation.invitee_id == invitee_id
        )
        if not include_deleted:
            stmt = stmt.where(TeamInvitation.deleted_at.is_(None))
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_for_team(
        self,
        team_id: UUID,
        *,
        page: int,
        page_size: int,
        status: Optional[TeamInvitationStatus] = None,
        sort_by: str = "created_at",
        sort_order: str = "desc",
    ) -> tuple[Sequence[TeamInvitation], int]:
        conditions = [TeamInvitation.team_id == team_id, TeamInvitation.deleted_at.is_(None)]
        if status is not None:
            conditions.append(TeamInvitation.status == status)

        sortable = {
            "created_at": TeamInvitation.created_at,
            "status": TeamInvitation.status,
            "responded_at": TeamInvitation.responded_at,
        }
        order_col = sortable.get(sort_by, TeamInvitation.created_at)
        order_fn = asc if sort_order.lower() == "asc" else desc

        count_stmt = select(func.count(TeamInvitation.id)).where(*conditions)
        total = (await self.session.execute(count_stmt)).scalar_one()

        stmt = (
            select(TeamInvitation)
            .where(*conditions)
            .order_by(order_fn(order_col))
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        rows = (await self.session.execute(stmt)).scalars().all()
        return rows, total

    async def list_incoming_for_user(
        self, invitee_id: UUID, *, page: int, page_size: int
    ) -> tuple[Sequence[TeamInvitation], int]:
        conditions = [
            TeamInvitation.invitee_id == invitee_id,
            TeamInvitation.status == TeamInvitationStatus.PENDING,
            TeamInvitation.deleted_at.is_(None),
        ]
        count_stmt = select(func.count(TeamInvitation.id)).where(*conditions)
        total = (await self.session.execute(count_stmt)).scalar_one()
        stmt = (
            select(TeamInvitation)
            .where(*conditions)
            .order_by(TeamInvitation.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        rows = (await self.session.execute(stmt)).scalars().all()
        return rows, total


class TeamJoinRequestRepository(BaseRepository[TeamJoinRequest]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, TeamJoinRequest)

    async def get_by_team_and_user(
        self, team_id: UUID, user_id: UUID, *, include_deleted: bool = False
    ) -> Optional[TeamJoinRequest]:
        stmt = select(TeamJoinRequest).where(
            TeamJoinRequest.team_id == team_id, TeamJoinRequest.user_id == user_id
        )
        if not include_deleted:
            stmt = stmt.where(TeamJoinRequest.deleted_at.is_(None))
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_for_team(
        self,
        team_id: UUID,
        *,
        page: int,
        page_size: int,
        status: Optional[TeamJoinRequestStatus] = None,
        sort_by: str = "created_at",
        sort_order: str = "desc",
    ) -> tuple[Sequence[TeamJoinRequest], int]:
        conditions = [TeamJoinRequest.team_id == team_id, TeamJoinRequest.deleted_at.is_(None)]
        if status is not None:
            conditions.append(TeamJoinRequest.status == status)

        sortable = {
            "created_at": TeamJoinRequest.created_at,
            "status": TeamJoinRequest.status,
            "responded_at": TeamJoinRequest.responded_at,
        }
        order_col = sortable.get(sort_by, TeamJoinRequest.created_at)
        order_fn = asc if sort_order.lower() == "asc" else desc

        count_stmt = select(func.count(TeamJoinRequest.id)).where(*conditions)
        total = (await self.session.execute(count_stmt)).scalar_one()

        stmt = (
            select(TeamJoinRequest)
            .where(*conditions)
            .order_by(order_fn(order_col))
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        rows = (await self.session.execute(stmt)).scalars().all()
        return rows, total

    async def list_outgoing_for_user(
        self, user_id: UUID, *, page: int, page_size: int
    ) -> tuple[Sequence[TeamJoinRequest], int]:
        conditions = [
            TeamJoinRequest.user_id == user_id,
            TeamJoinRequest.status == TeamJoinRequestStatus.PENDING,
            TeamJoinRequest.deleted_at.is_(None),
        ]
        count_stmt = select(func.count(TeamJoinRequest.id)).where(*conditions)
        total = (await self.session.execute(count_stmt)).scalar_one()
        stmt = (
            select(TeamJoinRequest)
            .where(*conditions)
            .order_by(TeamJoinRequest.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        rows = (await self.session.execute(stmt)).scalars().all()
        return rows, total


class TeamAnnouncementRepository(BaseRepository[TeamAnnouncement]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, TeamAnnouncement)

    async def list_for_team(
        self,
        team_id: UUID,
        *,
        page: int,
        page_size: int,
        pinned_only: bool = False,
        sort_order: str = "desc",
    ) -> tuple[Sequence[TeamAnnouncement], int]:
        conditions = [TeamAnnouncement.team_id == team_id, TeamAnnouncement.deleted_at.is_(None)]
        if pinned_only:
            conditions.append(TeamAnnouncement.is_pinned.is_(True))

        count_stmt = select(func.count(TeamAnnouncement.id)).where(*conditions)
        total = (await self.session.execute(count_stmt)).scalar_one()

        order_fn = asc if sort_order.lower() == "asc" else desc
        stmt = (
            select(TeamAnnouncement)
            .where(*conditions)
            .order_by(TeamAnnouncement.is_pinned.desc(), order_fn(TeamAnnouncement.created_at))
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        rows = (await self.session.execute(stmt)).scalars().all()
        return rows, total


class TeamActivityFeedRepository(BaseRepository[TeamActivityFeedEntry]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, TeamActivityFeedEntry)

    async def get_by_event_key(self, event_key: str) -> Optional[TeamActivityFeedEntry]:
        stmt = select(TeamActivityFeedEntry).where(TeamActivityFeedEntry.event_key == event_key)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_for_team(
        self,
        team_id: UUID,
        *,
        page: int,
        page_size: int,
        activity_types: Optional[Sequence[TeamActivityType]] = None,
        actor_id: Optional[UUID] = None,
        sort_order: str = "desc",
    ) -> tuple[Sequence[TeamActivityFeedEntry], int]:
        conditions = [
            TeamActivityFeedEntry.team_id == team_id,
            TeamActivityFeedEntry.deleted_at.is_(None),
        ]
        if activity_types:
            conditions.append(TeamActivityFeedEntry.activity_type.in_(activity_types))
        if actor_id is not None:
            conditions.append(TeamActivityFeedEntry.actor_id == actor_id)

        count_stmt = select(func.count(TeamActivityFeedEntry.id)).where(*conditions)
        total = (await self.session.execute(count_stmt)).scalar_one()

        order_fn = asc if sort_order.lower() == "asc" else desc
        stmt = (
            select(TeamActivityFeedEntry)
            .where(*conditions)
            .order_by(order_fn(TeamActivityFeedEntry.created_at))
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        rows = (await self.session.execute(stmt)).scalars().all()
        return rows, total
