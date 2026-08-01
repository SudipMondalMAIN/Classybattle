"""
Repositories for LoginHistory, SecurityEvent and AccountLock — Phase 16.
"""
from datetime import datetime, timedelta, timezone
from typing import Any, Optional, Sequence
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.security import AccountLock, LoginHistory, SecurityEvent, SecurityEventType


class LoginHistoryRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(self, **kwargs: Any) -> LoginHistory:
        instance = LoginHistory(**kwargs)
        self.session.add(instance)
        await self.session.flush()
        await self.session.refresh(instance)
        return instance

    async def list_for_user(
        self, user_id: UUID, skip: int = 0, limit: int = 50
    ) -> Sequence[LoginHistory]:
        stmt = (
            select(LoginHistory)
            .where(LoginHistory.user_id == user_id)
            .order_by(LoginHistory.created_at.desc())
            .offset(skip)
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def list_recent(self, skip: int = 0, limit: int = 50) -> Sequence[LoginHistory]:
        stmt = select(LoginHistory).order_by(LoginHistory.created_at.desc()).offset(skip).limit(limit)
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def known_devices_for_user(self, user_id: UUID) -> set[str]:
        stmt = (
            select(LoginHistory.device_id)
            .where(LoginHistory.user_id == user_id, LoginHistory.success.is_(True))
            .distinct()
        )
        result = await self.session.execute(stmt)
        return {row for row in result.scalars().all() if row}

    async def known_ips_for_user(self, user_id: UUID) -> set[str]:
        stmt = (
            select(LoginHistory.ip_address)
            .where(LoginHistory.user_id == user_id, LoginHistory.success.is_(True))
            .distinct()
        )
        result = await self.session.execute(stmt)
        return {row for row in result.scalars().all() if row}

    async def count_recent_failed_attempts(self, user_id: UUID, minutes: int = 15) -> int:
        since = datetime.now(timezone.utc) - timedelta(minutes=minutes)
        stmt = select(func.count()).select_from(LoginHistory).where(
            LoginHistory.user_id == user_id,
            LoginHistory.success.is_(False),
            LoginHistory.created_at >= since,
        )
        result = await self.session.execute(stmt)
        return int(result.scalar_one())

    async def users_sharing_ip(self, ip_address: str, exclude_user_id: Optional[UUID] = None) -> set[UUID]:
        stmt = select(LoginHistory.user_id).where(
            LoginHistory.ip_address == ip_address,
            LoginHistory.success.is_(True),
            LoginHistory.user_id.is_not(None),
        )
        result = await self.session.execute(stmt)
        ids = {row for row in result.scalars().all() if row}
        if exclude_user_id is not None:
            ids.discard(exclude_user_id)
        return ids

    async def users_sharing_device(self, device_id: str, exclude_user_id: Optional[UUID] = None) -> set[UUID]:
        if not device_id:
            return set()
        stmt = select(LoginHistory.user_id).where(
            LoginHistory.device_id == device_id,
            LoginHistory.success.is_(True),
            LoginHistory.user_id.is_not(None),
        )
        result = await self.session.execute(stmt)
        ids = {row for row in result.scalars().all() if row}
        if exclude_user_id is not None:
            ids.discard(exclude_user_id)
        return ids


class SecurityEventRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(self, **kwargs: Any) -> SecurityEvent:
        instance = SecurityEvent(**kwargs)
        self.session.add(instance)
        await self.session.flush()
        await self.session.refresh(instance)
        return instance

    async def get_by_id(self, event_id: UUID) -> Optional[SecurityEvent]:
        stmt = select(SecurityEvent).where(SecurityEvent.id == event_id)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_events(
        self,
        skip: int = 0,
        limit: int = 50,
        user_id: Optional[UUID] = None,
        event_type: Optional[SecurityEventType] = None,
        resolved: Optional[bool] = None,
    ) -> tuple[Sequence[SecurityEvent], int]:
        stmt = select(SecurityEvent)
        count_stmt = select(func.count()).select_from(SecurityEvent)

        if user_id is not None:
            stmt = stmt.where(SecurityEvent.user_id == user_id)
            count_stmt = count_stmt.where(SecurityEvent.user_id == user_id)
        if event_type is not None:
            stmt = stmt.where(SecurityEvent.event_type == event_type)
            count_stmt = count_stmt.where(SecurityEvent.event_type == event_type)
        if resolved is not None:
            stmt = stmt.where(SecurityEvent.resolved == resolved)
            count_stmt = count_stmt.where(SecurityEvent.resolved == resolved)

        stmt = stmt.order_by(SecurityEvent.created_at.desc()).offset(skip).limit(limit)

        total = (await self.session.execute(count_stmt)).scalar_one()
        result = await self.session.execute(stmt)
        return result.scalars().all(), int(total)

    async def resolve(self, instance: SecurityEvent, resolved_by: UUID) -> SecurityEvent:
        instance.resolved = True
        instance.resolved_by = resolved_by
        instance.resolved_at = datetime.now(timezone.utc)
        await self.session.flush()
        await self.session.refresh(instance)
        return instance


class AccountLockRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_user_id(self, user_id: UUID) -> Optional[AccountLock]:
        stmt = select(AccountLock).where(AccountLock.user_id == user_id)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_or_create(self, user_id: UUID) -> AccountLock:
        existing = await self.get_by_user_id(user_id)
        if existing is not None:
            return existing
        instance = AccountLock(user_id=user_id, is_locked=False, risk_score=0)
        self.session.add(instance)
        await self.session.flush()
        await self.session.refresh(instance)
        return instance

    async def update(self, instance: AccountLock, **kwargs: Any) -> AccountLock:
        for key, value in kwargs.items():
            setattr(instance, key, value)
        await self.session.flush()
        await self.session.refresh(instance)
        return instance

    async def list_locked(self, skip: int = 0, limit: int = 50) -> Sequence[AccountLock]:
        stmt = (
            select(AccountLock)
            .where(AccountLock.is_locked.is_(True))
            .order_by(AccountLock.locked_at.desc())
            .offset(skip)
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return result.scalars().all()
