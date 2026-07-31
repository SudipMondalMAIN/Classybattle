"""
WalletRepository — persistence for the Wallet aggregate.
"""
from typing import Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.wallet import Wallet
from app.repositories.base import BaseRepository


class WalletRepository(BaseRepository[Wallet]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, Wallet)

    async def get_by_user_id(self, user_id: UUID) -> Optional[Wallet]:
        stmt = select(Wallet).where(Wallet.user_id == user_id, Wallet.deleted_at.is_(None))
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_user_id_for_update(self, user_id: UUID) -> Optional[Wallet]:
        """Row-locking read used inside balance-mutating transactions to
        serialize concurrent credits/debits against the same wallet and
        prevent lost updates / negative-balance races.

        SQLite (used by the test suite) does not support SELECT ... FOR
        UPDATE, so the clause is skipped there; sqlite already serializes
        writers at the connection level, which is sufficient for tests.
        """
        stmt = select(Wallet).where(Wallet.user_id == user_id, Wallet.deleted_at.is_(None))
        if self.session.bind.dialect.name != "sqlite":
            stmt = stmt.with_for_update()
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()
