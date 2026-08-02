"""
Declarative base class and reusable mixins (id, timestamps, soft-delete).
"""
import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import BigInteger, DateTime, Sequence, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, declared_attr, mapped_column


class Base(DeclarativeBase):
    """Base class for all ORM models."""
    pass


class UUIDPrimaryKeyMixin:
    """Adds a UUID primary key column named `id`."""

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        unique=True,
        nullable=False,
    )


class TimestampMixin:
    """Adds created_at / updated_at columns, managed by the database."""

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class SoftDeleteMixin:
    """Adds a deleted_at column for soft deletes."""

    deleted_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        default=None,
    )

    @property
    def is_deleted(self) -> bool:
        return self.deleted_at is not None


class ShortIdMixin:
    """
    Adds a human-friendly `short_id` (e.g. 10000001) alongside the real
    UUID primary key. The UUID stays the actual primary/foreign key
    everywhere in the schema (no risk to relationships or referential
    integrity) — `short_id` exists purely so admins can search/read/type
    an ID easily instead of pasting a UUID. Each table gets its own
    dedicated sequence, starting at 10,000,001 (8 digits).
    """

    @declared_attr
    def short_id(cls) -> Mapped[int]:  # noqa: N805
        seq = Sequence(f"{cls.__tablename__}_short_id_seq", start=10_000_001, increment=1)
        return mapped_column(
            BigInteger,
            seq,
            server_default=seq.next_value(),
            unique=True,
            index=True,
            nullable=False,
        )


class BaseModel(UUIDPrimaryKeyMixin, TimestampMixin, SoftDeleteMixin, Base):
    """Abstract base combining id + timestamps + soft delete for all tables."""

    __abstract__ = True
