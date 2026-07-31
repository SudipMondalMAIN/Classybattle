"""
WalletTransactionRepository — persistence for the immutable wallet ledger.

Not built on `BaseRepository` because `WalletTransaction` intentionally
does not use the soft-delete mixin (ledger rows are append-only).
"""
from datetime import datetime
from typing import Any, Optional, Sequence
from uuid import UUID

from sqlalchemy import asc, desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.wallet_transaction import (
    WalletTransaction,
    WalletTransactionStatus,
    WalletTransactionType,
)

_SORTABLE_FIELDS = {
    "created_at": WalletTransaction.created_at,
    "amount": WalletTransaction.amount,
    "type": WalletTransaction.type,
    "status": WalletTransaction.status,
}


class WalletTransactionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(self, **kwargs: Any) -> WalletTransaction:
        instance = WalletTransaction(**kwargs)
        self.session.add(instance)
        await self.session.flush()
        await self.session.refresh(instance)
        return instance

    async def get_by_id(self, id_: UUID) -> Optional[WalletTransaction]:
        stmt = select(WalletTransaction).where(WalletTransaction.id == id_)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_reference(
        self, reference_type: str, reference_id: str, type_: WalletTransactionType
    ) -> Optional[WalletTransaction]:
        """Used for duplicate-transaction protection: a given (reference,
        type) pair may only ever produce one ledger row."""
        stmt = select(WalletTransaction).where(
            WalletTransaction.reference_type == reference_type,
            WalletTransaction.reference_id == reference_id,
            WalletTransaction.type == type_,
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def update_status(
        self, instance: WalletTransaction, status: WalletTransactionStatus
    ) -> WalletTransaction:
        instance.status = status
        await self.session.flush()
        await self.session.refresh(instance)
        return instance

    async def list_for_wallet(
        self,
        wallet_id: UUID,
        *,
        page: int = 1,
        page_size: int = 20,
        type_: Optional[WalletTransactionType] = None,
        status: Optional[WalletTransactionStatus] = None,
        date_from: Optional[datetime] = None,
        date_to: Optional[datetime] = None,
        sort_by: str = "created_at",
        sort_order: str = "desc",
    ) -> tuple[Sequence[WalletTransaction], int]:
        conditions = [WalletTransaction.wallet_id == wallet_id]
        if type_ is not None:
            conditions.append(WalletTransaction.type == type_)
        if status is not None:
            conditions.append(WalletTransaction.status == status)
        if date_from is not None:
            conditions.append(WalletTransaction.created_at >= date_from)
        if date_to is not None:
            conditions.append(WalletTransaction.created_at <= date_to)

        count_stmt = select(func.count()).select_from(WalletTransaction).where(*conditions)
        total = (await self.session.execute(count_stmt)).scalar_one()

        sort_column = _SORTABLE_FIELDS.get(sort_by, WalletTransaction.created_at)
        order_fn = asc if sort_order.lower() == "asc" else desc

        stmt = (
            select(WalletTransaction)
            .where(*conditions)
            .order_by(order_fn(sort_column))
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        result = await self.session.execute(stmt)
        return result.scalars().all(), total

    async def list_all_admin(
        self,
        *,
        page: int = 1,
        page_size: int = 20,
        user_id: Optional[UUID] = None,
        type_: Optional[WalletTransactionType] = None,
        status: Optional[WalletTransactionStatus] = None,
        date_from: Optional[datetime] = None,
        date_to: Optional[datetime] = None,
        sort_by: str = "created_at",
        sort_order: str = "desc",
    ) -> tuple[Sequence[WalletTransaction], int]:
        conditions = []
        if user_id is not None:
            conditions.append(WalletTransaction.user_id == user_id)
        if type_ is not None:
            conditions.append(WalletTransaction.type == type_)
        if status is not None:
            conditions.append(WalletTransaction.status == status)
        if date_from is not None:
            conditions.append(WalletTransaction.created_at >= date_from)
        if date_to is not None:
            conditions.append(WalletTransaction.created_at <= date_to)

        count_stmt = select(func.count()).select_from(WalletTransaction).where(*conditions)
        total = (await self.session.execute(count_stmt)).scalar_one()

        sort_column = _SORTABLE_FIELDS.get(sort_by, WalletTransaction.created_at)
        order_fn = asc if sort_order.lower() == "asc" else desc

        stmt = (
            select(WalletTransaction)
            .where(*conditions)
            .order_by(order_fn(sort_column))
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        result = await self.session.execute(stmt)
        return result.scalars().all(), total
