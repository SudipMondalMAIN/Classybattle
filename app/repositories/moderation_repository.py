"""
Repositories for Report/ModerationAction/Appeal — Phase 15C.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional, Sequence
from uuid import UUID

from sqlalchemy import and_, desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.moderation import (
    Appeal,
    AppealStatus,
    ModerationAction,
    ModerationActionStatus,
    Report,
    ReportStatus,
    ReportTargetType,
)
from app.repositories.base import BaseRepository


class ReportRepository(BaseRepository[Report]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, Report)

    async def list_paginated(
        self,
        *,
        page: int = 1,
        page_size: int = 20,
        target_type: Optional[ReportTargetType] = None,
        status: Optional[ReportStatus] = None,
        reporter_id: Optional[UUID] = None,
    ) -> tuple[Sequence[Report], int]:
        conditions = [Report.deleted_at.is_(None)]
        if target_type is not None:
            conditions.append(Report.target_type == target_type)
        if status is not None:
            conditions.append(Report.status == status)
        if reporter_id is not None:
            conditions.append(Report.reporter_id == reporter_id)

        count_stmt = select(func.count(Report.id)).where(and_(*conditions))
        total = (await self.session.execute(count_stmt)).scalar_one()

        stmt = (
            select(Report)
            .where(and_(*conditions))
            .order_by(desc(Report.created_at))
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        result = await self.session.execute(stmt)
        return result.scalars().all(), total

    async def get_by_short_id(self, short_id: int) -> Optional[Report]:
        stmt = select(Report).where(Report.short_id == short_id, Report.deleted_at.is_(None))
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def count_recent_for_target(
        self, target_type: ReportTargetType, target_id: UUID, since: datetime
    ) -> int:
        stmt = select(func.count(Report.id)).where(
            Report.target_type == target_type,
            Report.target_id == target_id,
            Report.created_at >= since,
            Report.deleted_at.is_(None),
        )
        return (await self.session.execute(stmt)).scalar_one()


class ModerationActionRepository(BaseRepository[ModerationAction]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, ModerationAction)

    async def list_for_user(self, user_id: UUID) -> Sequence[ModerationAction]:
        stmt = (
            select(ModerationAction)
            .where(ModerationAction.user_id == user_id, ModerationAction.deleted_at.is_(None))
            .order_by(desc(ModerationAction.created_at))
        )
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def get_by_short_id(self, short_id: int) -> Optional[ModerationAction]:
        stmt = select(ModerationAction).where(
            ModerationAction.short_id == short_id, ModerationAction.deleted_at.is_(None)
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_active_for_user(self, user_id: UUID) -> Sequence[ModerationAction]:
        stmt = select(ModerationAction).where(
            ModerationAction.user_id == user_id,
            ModerationAction.status == ModerationActionStatus.ACTIVE,
            ModerationAction.deleted_at.is_(None),
        )
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def list_paginated(
        self, *, page: int = 1, page_size: int = 20, user_id: Optional[UUID] = None
    ) -> tuple[Sequence[ModerationAction], int]:
        conditions = [ModerationAction.deleted_at.is_(None)]
        if user_id is not None:
            conditions.append(ModerationAction.user_id == user_id)

        count_stmt = select(func.count(ModerationAction.id)).where(and_(*conditions))
        total = (await self.session.execute(count_stmt)).scalar_one()

        stmt = (
            select(ModerationAction)
            .where(and_(*conditions))
            .order_by(desc(ModerationAction.created_at))
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        result = await self.session.execute(stmt)
        return result.scalars().all(), total

    async def list_expired_active(self, as_of: Optional[datetime] = None) -> Sequence[ModerationAction]:
        as_of = as_of or datetime.now(timezone.utc)
        stmt = select(ModerationAction).where(
            ModerationAction.status == ModerationActionStatus.ACTIVE,
            ModerationAction.expires_at.is_not(None),
            ModerationAction.expires_at <= as_of,
        )
        result = await self.session.execute(stmt)
        return result.scalars().all()


class AppealRepository(BaseRepository[Appeal]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, Appeal)

    async def get_pending_for_action(self, moderation_action_id: UUID) -> Optional[Appeal]:
        stmt = select(Appeal).where(
            Appeal.moderation_action_id == moderation_action_id,
            Appeal.status == AppealStatus.PENDING,
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_paginated(
        self, *, page: int = 1, page_size: int = 20, status: Optional[AppealStatus] = None
    ) -> tuple[Sequence[Appeal], int]:
        conditions = [Appeal.deleted_at.is_(None)]
        if status is not None:
            conditions.append(Appeal.status == status)

        count_stmt = select(func.count(Appeal.id)).where(and_(*conditions))
        total = (await self.session.execute(count_stmt)).scalar_one()

        stmt = (
            select(Appeal)
            .where(and_(*conditions))
            .order_by(desc(Appeal.created_at))
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        result = await self.session.execute(stmt)
        return result.scalars().all(), total

    async def list_for_user(self, user_id: UUID) -> Sequence[Appeal]:
        stmt = (
            select(Appeal)
            .where(Appeal.user_id == user_id, Appeal.deleted_at.is_(None))
            .order_by(desc(Appeal.created_at))
        )
        result = await self.session.execute(stmt)
        return result.scalars().all()
