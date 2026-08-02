"""
Moderation models — Phase 15C (Achievements & Moderation).

- `Report` — a single flexible reporting table covering Player, Team and
  Match reports (distinguished by `target_type` + `target_id`), mirroring
  how `AuditLog` uses a generic `entity`/`entity_id` pair instead of one
  table per entity type.
- `ModerationAction` — Warning / Suspension / Ban issued against a user,
  optionally originating from a `Report`. Suspension/Ban actions carry an
  `expires_at` for time-boxed enforcement; a null `expires_at` on a BAN
  means permanent.
- `Appeal` — a user's appeal against a `ModerationAction`, reviewed by an
  admin.
"""
import enum
import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, Enum, ForeignKey, Index, String
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import BaseModel, ShortIdMixin
from app.database.types import PortableJSONB, str_enum


class ReportTargetType(str, enum.Enum):
    PLAYER = "player"
    TEAM = "team"
    MATCH = "match"


class ReportReason(str, enum.Enum):
    CHEATING = "cheating"
    HARASSMENT = "harassment"
    ABUSIVE_LANGUAGE = "abusive_language"
    NO_SHOW = "no_show"
    MATCH_FIXING = "match_fixing"
    IMPERSONATION = "impersonation"
    SPAM = "spam"
    OTHER = "other"


class ReportStatus(str, enum.Enum):
    PENDING = "pending"
    UNDER_REVIEW = "under_review"
    RESOLVED = "resolved"
    DISMISSED = "dismissed"


class ModerationActionType(str, enum.Enum):
    WARNING = "warning"
    SUSPENSION = "suspension"
    BAN = "ban"


class ModerationActionStatus(str, enum.Enum):
    ACTIVE = "active"
    EXPIRED = "expired"
    REVOKED = "revoked"


class AppealStatus(str, enum.Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class Report(ShortIdMixin, BaseModel):
    __tablename__ = "reports"
    __table_args__ = (
        Index("ix_reports_target", "target_type", "target_id"),
    )

    reporter_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    target_type: Mapped[ReportTargetType] = mapped_column(
        str_enum(ReportTargetType, "report_target_type"), nullable=False
    )
    # Polymorphic reference — user_id for PLAYER, team_id for TEAM,
    # match_id for MATCH. Kept as a bare UUID (no FK) since it points at
    # different tables depending on `target_type`, same approach as
    # AuditLog.entity_id.
    target_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False, index=True)

    reason: Mapped[ReportReason] = mapped_column(
        str_enum(ReportReason, "report_reason"), nullable=False
    )
    description: Mapped[Optional[str]] = mapped_column(String(2000), nullable=True)
    status: Mapped[ReportStatus] = mapped_column(
        str_enum(ReportStatus, "report_status"), default=ReportStatus.PENDING, nullable=False, index=True
    )
    evidence_urls: Mapped[Optional[dict]] = mapped_column(PortableJSONB, nullable=True)

    reviewed_by_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    reviewed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    resolution_notes: Mapped[Optional[str]] = mapped_column(String(2000), nullable=True)

    def __repr__(self) -> str:
        return f"<Report id={self.id} target_type={self.target_type} target_id={self.target_id}>"


class ModerationAction(ShortIdMixin, BaseModel):
    __tablename__ = "moderation_actions"

    user_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    action_type: Mapped[ModerationActionType] = mapped_column(
        str_enum(ModerationActionType, "moderation_action_type"), nullable=False, index=True
    )
    status: Mapped[ModerationActionStatus] = mapped_column(
        str_enum(ModerationActionStatus, "moderation_action_status"),
        default=ModerationActionStatus.ACTIVE,
        nullable=False,
        index=True,
    )
    reason: Mapped[str] = mapped_column(String(1000), nullable=False)
    report_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("reports.id", ondelete="SET NULL"), nullable=True
    )
    issued_by_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_reason: Mapped[Optional[str]] = mapped_column(String(1000), nullable=True)

    user: Mapped["User"] = relationship(  # noqa: F821
        foreign_keys=[user_id], lazy="selectin"
    )

    def __repr__(self) -> str:
        return f"<ModerationAction id={self.id} user_id={self.user_id} type={self.action_type}>"


class Appeal(BaseModel):
    __tablename__ = "appeals"

    moderation_action_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("moderation_actions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    message: Mapped[str] = mapped_column(String(2000), nullable=False)
    status: Mapped[AppealStatus] = mapped_column(
        str_enum(AppealStatus, "appeal_status"), default=AppealStatus.PENDING, nullable=False, index=True
    )
    reviewed_by_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    reviewed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    review_notes: Mapped[Optional[str]] = mapped_column(String(2000), nullable=True)

    def __repr__(self) -> str:
        return f"<Appeal id={self.id} moderation_action_id={self.moderation_action_id}>"
