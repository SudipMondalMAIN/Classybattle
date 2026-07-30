"""
Generic async repository providing common CRUD operations.
Concrete repositories subclass this for model-specific queries.
"""
from datetime import datetime, timezone
from typing import Any, Generic, Optional, Sequence, Type, TypeVar
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.base import BaseModel

ModelType = TypeVar("ModelType", bound=BaseModel)


class BaseRepository(Generic[ModelType]):
    """Generic repository implementing the Repository Pattern over a single model."""

    model: Type[ModelType]

    def __init__(self, session: AsyncSession, model: Type[ModelType]) -> None:
        self.session = session
        self.model = model

    async def get_by_id(self, id_: UUID, include_deleted: bool = False) -> Optional[ModelType]:
        stmt = select(self.model).where(self.model.id == id_)
        if not include_deleted:
            stmt = stmt.where(self.model.deleted_at.is_(None))
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_all(
        self, skip: int = 0, limit: int = 100, include_deleted: bool = False
    ) -> Sequence[ModelType]:
        stmt = select(self.model).offset(skip).limit(limit)
        if not include_deleted:
            stmt = stmt.where(self.model.deleted_at.is_(None))
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def create(self, **kwargs: Any) -> ModelType:
        instance = self.model(**kwargs)
        self.session.add(instance)
        await self.session.flush()
        await self.session.refresh(instance)
        return instance

    async def update(self, instance: ModelType, **kwargs: Any) -> ModelType:
        for key, value in kwargs.items():
            setattr(instance, key, value)
        await self.session.flush()
        await self.session.refresh(instance)
        return instance

    async def soft_delete(self, instance: ModelType) -> ModelType:
        instance.deleted_at = datetime.now(timezone.utc)
        await self.session.flush()
        return instance

    async def hard_delete(self, instance: ModelType) -> None:
        await self.session.delete(instance)
        await self.session.flush()
