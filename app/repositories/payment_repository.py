"""
Repositories for the manual payment verification system — Phase 17.
"""
from datetime import datetime
from typing import Any, Optional, Sequence
from uuid import UUID

from sqlalchemy import asc, desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.payment import (
    PaymentProvider,
    PaymentRequest,
    PaymentRequestStatus,
    PaymentSettings,
)

_SORTABLE_FIELDS = {
    "created_at": PaymentRequest.created_at,
    "submitted_at": PaymentRequest.submitted_at,
    "amount": PaymentRequest.amount,
    "status": PaymentRequest.status,
    "verified_at": PaymentRequest.verified_at,
}


class PaymentSettingsRepository:
    """Persistence for the single PaymentSettings row."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_singleton(self) -> Optional[PaymentSettings]:
        stmt = select(PaymentSettings).order_by(PaymentSettings.created_at.asc()).limit(1)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def create(self, **kwargs: Any) -> PaymentSettings:
        instance = PaymentSettings(**kwargs)
        self.session.add(instance)
        await self.session.flush()
        await self.session.refresh(instance)
        return instance

    async def update(self, instance: PaymentSettings, **kwargs: Any) -> PaymentSettings:
        for key, value in kwargs.items():
            setattr(instance, key, value)
        await self.session.flush()
        await self.session.refresh(instance)
        return instance


class PaymentRequestRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(self, **kwargs: Any) -> PaymentRequest:
        instance = PaymentRequest(**kwargs)
        self.session.add(instance)
        await self.session.flush()
        await self.session.refresh(instance)
        return instance

    async def get_by_id(self, id_: UUID) -> Optional[PaymentRequest]:
        stmt = select(PaymentRequest).where(
            PaymentRequest.id == id_, PaymentRequest.deleted_at.is_(None)
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_id_for_update(self, id_: UUID) -> Optional[PaymentRequest]:
        """Row-locking read used inside the admin verification transaction
        to serialize concurrent approve/reject/hold calls on the same
        request and guarantee idempotent, exactly-once verification.

        SQLite (test suite) does not support SELECT ... FOR UPDATE.
        """
        stmt = select(PaymentRequest).where(
            PaymentRequest.id == id_, PaymentRequest.deleted_at.is_(None)
        )
        if self.session.bind.dialect.name != "sqlite":
            stmt = stmt.with_for_update()
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_short_id(self, short_id: int) -> Optional[PaymentRequest]:
        stmt = select(PaymentRequest).where(
            PaymentRequest.short_id == short_id, PaymentRequest.deleted_at.is_(None)
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_utr(self, utr_number: str) -> Optional[PaymentRequest]:
        stmt = select(PaymentRequest).where(PaymentRequest.utr_number == utr_number)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def update(self, instance: PaymentRequest, **kwargs: Any) -> PaymentRequest:
        for key, value in kwargs.items():
            setattr(instance, key, value)
        await self.session.flush()
        await self.session.refresh(instance)
        return instance

    async def list_for_user(
        self,
        user_id: UUID,
        *,
        page: int = 1,
        page_size: int = 20,
        status: Optional[PaymentRequestStatus] = None,
        sort_by: str = "created_at",
        sort_order: str = "desc",
    ) -> tuple[Sequence[PaymentRequest], int]:
        conditions = [PaymentRequest.user_id == user_id, PaymentRequest.deleted_at.is_(None)]
        if status is not None:
            conditions.append(PaymentRequest.status == status)

        count_stmt = select(func.count()).select_from(PaymentRequest).where(*conditions)
        total = (await self.session.execute(count_stmt)).scalar_one()

        sort_column = _SORTABLE_FIELDS.get(sort_by, PaymentRequest.created_at)
        order_fn = asc if sort_order.lower() == "asc" else desc

        stmt = (
            select(PaymentRequest)
            .where(*conditions)
            .order_by(order_fn(sort_column))
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        result = await self.session.execute(stmt)
        return result.scalars().all(), total

    async def list_admin(
        self,
        *,
        page: int = 1,
        page_size: int = 20,
        user_id: Optional[UUID] = None,
        status: Optional[PaymentRequestStatus] = None,
        provider: Optional[PaymentProvider] = None,
        date_from: Optional[datetime] = None,
        date_to: Optional[datetime] = None,
        sort_by: str = "created_at",
        sort_order: str = "desc",
    ) -> tuple[Sequence[PaymentRequest], int]:
        conditions = [PaymentRequest.deleted_at.is_(None)]
        if user_id is not None:
            conditions.append(PaymentRequest.user_id == user_id)
        if status is not None:
            conditions.append(PaymentRequest.status == status)
        if provider is not None:
            conditions.append(PaymentRequest.provider == provider)
        if date_from is not None:
            conditions.append(PaymentRequest.submitted_at >= date_from)
        if date_to is not None:
            conditions.append(PaymentRequest.submitted_at <= date_to)

        count_stmt = select(func.count()).select_from(PaymentRequest).where(*conditions)
        total = (await self.session.execute(count_stmt)).scalar_one()

        sort_column = _SORTABLE_FIELDS.get(sort_by, PaymentRequest.created_at)
        order_fn = asc if sort_order.lower() == "asc" else desc

        stmt = (
            select(PaymentRequest)
            .where(*conditions)
            .order_by(order_fn(sort_column))
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        result = await self.session.execute(stmt)
        return result.scalars().all(), total
