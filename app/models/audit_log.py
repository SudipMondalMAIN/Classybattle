"""
AuditLog model — Phase 7.5 (Backend Hardening).

A single, reusable audit trail for every sensitive mutation performed by a
User, Admin or Organizer. Designed to be append-only: rows are never
updated or deleted by application code. Future Wallet/Payment modules
reuse this exact table rather than creating their own audit mechanism.
"""
import enum
import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, Enum, ForeignKey, Index, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.database.base import Base
from app.database.types import PortableJSONB


class AuditActorType(str, enum.Enum):
    """Who performed the action. Kept separate from `User.role` because a
    single user's role can change over time, while the actor type recorded
    on an audit row must reflect the capacity they acted in at that time."""

    USER = "user"
    ADMIN = "admin"
    ORGANIZER = "organizer"
    SYSTEM = "system"


class AuditAction(str, enum.Enum):
    CREATE = "create"
    UPDATE = "update"
    DELETE = "delete"
    STATUS_CHANGE = "status_change"
    LOGIN = "login"
    LOGOUT = "logout"
    PERMISSION_CHANGE = "permission_change"
    OTHER = "other"


class AuditLog(Base):
    """Append-only audit trail. Intentionally does NOT inherit BaseModel's
    soft-delete/updated_at mixins — audit rows are immutable by design."""

    __tablename__ = "audit_logs"
    __table_args__ = (
        Index("ix_audit_logs_entity_type_id", "entity", "entity_id"),
        Index("ix_audit_logs_actor", "actor_id", "actor_type"),
        Index("ix_audit_logs_created_at", "created_at"),
        Index("ix_audit_logs_request_id", "request_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, nullable=False
    )

    # ---- Actor (User / Admin / Organizer / System) ----
    actor_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    actor_type: Mapped[AuditActorType] = mapped_column(
        Enum(AuditActorType, name="audit_actor_type"), nullable=False
    )
    # Denormalized snapshot so the log stays meaningful even if the user
    # row is later modified, deleted, or the FK above is nulled out.
    actor_label: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    # ---- What happened ----
    action: Mapped[AuditAction] = mapped_column(
        Enum(AuditAction, name="audit_action"), nullable=False, index=True
    )
    entity: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    entity_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)

    old_values: Mapped[Optional[dict]] = mapped_column(PortableJSONB, nullable=True)
    new_values: Mapped[Optional[dict]] = mapped_column(PortableJSONB, nullable=True)

    # ---- Request metadata ----
    ip_address: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    request_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)

    description: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    actor: Mapped[Optional["User"]] = relationship(lazy="selectin")  # noqa: F821

    def __repr__(self) -> str:
        return (
            f"<AuditLog id={self.id} entity={self.entity} "
            f"entity_id={self.entity_id} action={self.action}>"
        )
