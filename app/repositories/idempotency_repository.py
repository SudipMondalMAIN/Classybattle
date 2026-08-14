"""
IdempotencyKeyRepository — persistence for replay-protection records.
"""
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.idempotency_key import IdempotencyKey, IdempotencyKeyStatus


class IdempotencyKeyRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, scope: str, key: str, user_id: Optional[Any] = None) -> Optional[IdempotencyKey]:
        stmt = select(IdempotencyKey).where(
            IdempotencyKey.scope == scope, IdempotencyKey.key == key
        )
        if user_id is not None:
            stmt = stmt.where(IdempotencyKey.user_id == user_id)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def create(self, **kwargs: Any) -> IdempotencyKey:
        instance = IdempotencyKey(**kwargs)
        self.session.add(instance)
        await self.session.flush()
        await self.session.refresh(instance)
        return instance

    async def mark_completed(
        self, instance: IdempotencyKey, *, status_code: int, body: Optional[dict]
    ) -> IdempotencyKey:
        instance.status = IdempotencyKeyStatus.COMPLETED
        instance.response_status_code = status_code
        instance.response_body = body
        instance.completed_at = datetime.now(timezone.utc)
        await self.session.flush()
        return instance

    async def mark_failed(self, instance: IdempotencyKey) -> IdempotencyKey:
        instance.status = IdempotencyKeyStatus.FAILED
        instance.completed_at = datetime.now(timezone.utc)
        await self.session.flush()
        return instance

    async def delete_expired(self, before: datetime) -> int:
        stmt = select(IdempotencyKey).where(IdempotencyKey.expires_at < before)
        result = await self.session.execute(stmt)
        rows = result.scalars().all()
        for row in rows:
            await self.session.delete(row)
        await self.session.flush()
        return len(rows)