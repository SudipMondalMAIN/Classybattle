"""
AuditLogRepository — persistence for the append-only audit trail.

Not built on `BaseRepository` because `AuditLog` intentionally does not
use the soft-delete/updated_at mixins (audit rows are immutable).
"""
from typing import Any, Optional, Sequence
from uuid import UUID

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit_log import AuditAction, AuditActorType, AuditLog


class AuditLogRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(self, **kwargs: Any) -> AuditLog:
        instance = AuditLog(**kwargs)
        self.session.add(instance)
        await self.session.flush()
        await self.session.refresh(instance)
        return instance

    async def list_for_entity(
        self, entity: str, entity_id: str, skip: int = 0, limit: int = 100
    ) -> Sequence[AuditLog]:
        stmt = (
            select(AuditLog)
            .where(AuditLog.entity == entity, AuditLog.entity_id == entity_id)
            .order_by(desc(AuditLog.created_at))
            .offset(skip)
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def list_for_actor(
        self, actor_id: UUID, skip: int = 0, limit: int = 100
    ) -> Sequence[AuditLog]:
        stmt = (
            select(AuditLog)
            .where(AuditLog.actor_id == actor_id)
            .order_by(desc(AuditLog.created_at))
            .offset(skip)
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def search(
        self,
        *,
        entity: Optional[str] = None,
        action: Optional[AuditAction] = None,
        actor_type: Optional[AuditActorType] = None,
        skip: int = 0,
        limit: int = 100,
    ) -> Sequence[AuditLog]:
        stmt = select(AuditLog)
        if entity is not None:
            stmt = stmt.where(AuditLog.entity == entity)
        if action is not None:
            stmt = stmt.where(AuditLog.action == action)
        if actor_type is not None:
            stmt = stmt.where(AuditLog.actor_type == actor_type)
        stmt = stmt.order_by(desc(AuditLog.created_at)).offset(skip).limit(limit)
        result = await self.session.execute(stmt)
        return result.scalars().all()
