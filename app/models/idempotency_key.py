"""
IdempotencyKey model — Phase 7.5 (Backend Hardening).

Reusable infrastructure so future payment/wallet endpoints can safely
accept a client-supplied `Idempotency-Key` header and guarantee
"exactly-once" processing semantics on retried requests. No payment
business logic lives here — this is purely the storage + replay-protection
primitive; endpoints that need it wrap themselves with
`app.core.idempotency.idempotent`.
"""
import enum
import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, Enum, ForeignKey, Index, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.database.base import Base
from app.database.types import PortableJSONB, str_enum


class IdempotencyKeyStatus(str, enum.Enum):
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"


class IdempotencyKey(Base):
    """One row per (user, endpoint scope, idempotency key).

    - A key is first inserted with status=IN_PROGRESS before the wrapped
      handler runs (row-level uniqueness gives us the replay lock).
    - On success it is updated to COMPLETED with the response snapshot so a
      retried request can be answered without re-executing side effects.
    - On failure it is updated to FAILED so a subsequent retry with the
      SAME key is allowed to run again (idempotency keys protect against
      duplicate *successful* processing, not against retrying failures).
    """

    __tablename__ = "idempotency_keys"
    __table_args__ = (
        UniqueConstraint("scope", "key", name="uq_idempotency_scope_key"),
        Index("ix_idempotency_keys_user", "user_id"),
        Index("ix_idempotency_keys_created_at", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, nullable=False
    )

    # `scope` namespaces keys per endpoint/use-case (e.g. "wallet.topup",
    # "payment.checkout") so two different APIs can't collide on the same
    # client-generated key.
    scope: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    key: Mapped[str] = mapped_column(String(255), nullable=False)

    user_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=True
    )

    # SHA-256 hex digest of the request body. Used to detect a client
    # reusing the same idempotency key with a *different* payload, which
    # must be rejected rather than silently replayed.
    request_fingerprint: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)

    status: Mapped[IdempotencyKeyStatus] = mapped_column(
        str_enum(IdempotencyKeyStatus, "idempotency_key_status"),
        default=IdempotencyKeyStatus.IN_PROGRESS,
        nullable=False,
    )

    response_status_code: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    response_body: Mapped[Optional[dict]] = mapped_column(PortableJSONB, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    locked_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    # Idempotency records are kept only long enough to protect against
    # client-side retries; a scheduled cleanup job can purge rows where
    # expires_at < now().
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    user: Mapped[Optional["User"]] = relationship(lazy="selectin")  # noqa: F821

    def __repr__(self) -> str:
        return f"<IdempotencyKey id={self.id} scope={self.scope} status={self.status}>"
