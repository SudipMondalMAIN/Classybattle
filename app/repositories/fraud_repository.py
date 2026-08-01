"""
FraudFlagRepository — Phase 16 (Anti-Cheat).
"""
from typing import Any, Optional, Sequence
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.security import FraudFlag, FraudFlagStatus, FraudFlagType


class FraudFlagRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_existing_open(
        self,
        user_id: UUID,
        flag_type: FraudFlagType,
        related_entity_type: str = "none",
        related_entity_id: str = "",
    ) -> Optional[FraudFlag]:
        stmt = select(FraudFlag).where(
            FraudFlag.user_id == user_id,
            FraudFlag.flag_type == flag_type,
            FraudFlag.related_entity_type == related_entity_type,
            FraudFlag.related_entity_id == related_entity_id,
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def create_if_not_exists(
        self,
        *,
        user_id: UUID,
        flag_type: FraudFlagType,
        risk_score: int = 0,
        related_entity_type: str = "none",
        related_entity_id: str = "",
        details: Optional[dict] = None,
        description: Optional[str] = None,
    ) -> tuple[FraudFlag, bool]:
        """Idempotently create a fraud flag. Returns (flag, created)."""
        existing = await self.get_existing_open(user_id, flag_type, related_entity_type, related_entity_id)
        if existing is not None:
            return existing, False

        stmt = (
            pg_insert(FraudFlag)
            .values(
                user_id=user_id,
                flag_type=flag_type,
                status=FraudFlagStatus.OPEN,
                risk_score=risk_score,
                related_entity_type=related_entity_type,
                related_entity_id=related_entity_id,
                details=details,
                description=description,
            )
            .on_conflict_do_nothing(
                constraint="uq_fraud_flags_user_type_entity",
            )
            .returning(FraudFlag)
        )
        result = await self.session.execute(stmt)
        row = result.scalar_one_or_none()
        await self.session.flush()
        if row is not None:
            return row, True

        # Conflict happened concurrently — fetch the existing row.
        existing = await self.get_existing_open(user_id, flag_type, related_entity_type, related_entity_id)
        return existing, False  # type: ignore[return-value]

    async def get_by_id(self, flag_id: UUID) -> Optional[FraudFlag]:
        stmt = select(FraudFlag).where(FraudFlag.id == flag_id)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_flags(
        self,
        skip: int = 0,
        limit: int = 50,
        status: Optional[FraudFlagStatus] = None,
        flag_type: Optional[FraudFlagType] = None,
        user_id: Optional[UUID] = None,
    ) -> tuple[Sequence[FraudFlag], int]:
        stmt = select(FraudFlag)
        count_stmt = select(func.count()).select_from(FraudFlag)

        if status is not None:
            stmt = stmt.where(FraudFlag.status == status)
            count_stmt = count_stmt.where(FraudFlag.status == status)
        if flag_type is not None:
            stmt = stmt.where(FraudFlag.flag_type == flag_type)
            count_stmt = count_stmt.where(FraudFlag.flag_type == flag_type)
        if user_id is not None:
            stmt = stmt.where(FraudFlag.user_id == user_id)
            count_stmt = count_stmt.where(FraudFlag.user_id == user_id)

        stmt = stmt.order_by(FraudFlag.created_at.desc()).offset(skip).limit(limit)

        total = (await self.session.execute(count_stmt)).scalar_one()
        result = await self.session.execute(stmt)
        return result.scalars().all(), int(total)

    async def update(self, instance: FraudFlag, **kwargs: Any) -> FraudFlag:
        for key, value in kwargs.items():
            setattr(instance, key, value)
        await self.session.flush()
        await self.session.refresh(instance)
        return instance
