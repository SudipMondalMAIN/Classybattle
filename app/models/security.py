"""
Security / Anti-Cheat / Analytics models — Phase 16.

Covers:
- LoginHistory: every login attempt (success or failure) with device/IP metadata.
- SecurityEvent: append-only security audit trail (suspicious logins, lockouts, etc).
- AccountLock: current lock state for a user (1:1).
- FraudFlag: anti-cheat flags raised against a user/entity, deduplicated.
- AnalyticsSnapshot: cached daily/weekly/monthly aggregate metrics for the
  admin dashboard & analytics endpoints, deduplicated per (metric, period).
"""
import enum
import uuid
from datetime import date, datetime
from typing import Optional

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base, BaseModel
from app.database.types import PortableJSONB, str_enum


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------
class SecurityEventType(str, enum.Enum):
    SUSPICIOUS_LOGIN = "suspicious_login"
    NEW_DEVICE_LOGIN = "new_device_login"
    MULTIPLE_FAILED_LOGINS = "multiple_failed_logins"
    ACCOUNT_LOCKED = "account_locked"
    ACCOUNT_UNLOCKED = "account_unlocked"
    RISK_SCORE_UPDATED = "risk_score_updated"
    DUPLICATE_ACCOUNT = "duplicate_account"
    DUPLICATE_TEAM = "duplicate_team"
    MULTIPLE_REGISTRATION = "multiple_registration"
    MATCH_ABUSE = "match_abuse"
    WALLET_ABUSE = "wallet_abuse"
    OTHER = "other"


class SecurityEventSeverity(str, enum.Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class FraudFlagType(str, enum.Enum):
    DUPLICATE_ACCOUNT = "duplicate_account"
    MULTIPLE_REGISTRATION = "multiple_registration"
    DUPLICATE_TEAM = "duplicate_team"
    MATCH_ABUSE = "match_abuse"
    WALLET_ABUSE = "wallet_abuse"
    SUSPICIOUS_ACTIVITY = "suspicious_activity"


class FraudFlagStatus(str, enum.Enum):
    OPEN = "open"
    REVIEWING = "reviewing"
    CONFIRMED = "confirmed"
    DISMISSED = "dismissed"


class AnalyticsMetricType(str, enum.Enum):
    USER = "user"
    TOURNAMENT = "tournament"
    MATCH = "match"
    WALLET = "wallet"
    REVENUE = "revenue"
    PRIZE = "prize"
    REGISTRATION = "registration"
    DASHBOARD = "dashboard"


class AnalyticsPeriodType(str, enum.Enum):
    DAILY = "daily"
    WEEKLY = "weekly"
    MONTHLY = "monthly"
    CUSTOM = "custom"


# ---------------------------------------------------------------------------
# LoginHistory
# ---------------------------------------------------------------------------
class LoginHistory(Base):
    """Append-only login attempt log. Not soft-deletable by design."""

    __tablename__ = "login_history"
    __table_args__ = (
        Index("ix_login_history_user_created", "user_id", "created_at"),
        Index("ix_login_history_ip", "ip_address"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, nullable=False
    )
    user_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    email_attempted: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    success: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    failure_reason: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    ip_address: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, index=True)
    user_agent: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    device_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    platform: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)

    is_new_device: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_new_ip: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_suspicious: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    risk_score: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now()
    )

    user: Mapped[Optional["User"]] = relationship(lazy="selectin")  # noqa: F821

    def __repr__(self) -> str:
        return f"<LoginHistory id={self.id} user_id={self.user_id} success={self.success}>"


# ---------------------------------------------------------------------------
# SecurityEvent
# ---------------------------------------------------------------------------
class SecurityEvent(Base):
    """Append-only security audit log, separate from the generic AuditLog
    (which tracks business-entity mutations) so security tooling / SIEM
    export can query a focused, high-signal table."""

    __tablename__ = "security_events"
    __table_args__ = (
        Index("ix_security_events_user_created", "user_id", "created_at"),
        Index("ix_security_events_type", "event_type"),
        Index("ix_security_events_resolved", "resolved"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, nullable=False
    )
    user_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    event_type: Mapped[SecurityEventType] = mapped_column(
        str_enum(SecurityEventType, "security_event_type"), nullable=False
    )
    severity: Mapped[SecurityEventSeverity] = mapped_column(
        str_enum(SecurityEventSeverity, "security_event_severity"),
        nullable=False,
        default=SecurityEventSeverity.LOW,
    )
    description: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    event_metadata: Mapped[Optional[dict]] = mapped_column(PortableJSONB, nullable=True)
    ip_address: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)

    resolved: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    resolved_by: Mapped[Optional[uuid.UUID]] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    resolved_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now()
    )

    user: Mapped[Optional["User"]] = relationship(  # noqa: F821
        foreign_keys=[user_id], lazy="selectin"
    )

    def __repr__(self) -> str:
        return f"<SecurityEvent id={self.id} type={self.event_type} severity={self.severity}>"


# ---------------------------------------------------------------------------
# AccountLock
# ---------------------------------------------------------------------------
class AccountLock(BaseModel):
    """Current lock state for a user account. One row per user."""

    __tablename__ = "account_locks"
    __table_args__ = (UniqueConstraint("user_id", name="uq_account_locks_user_id"),)

    user_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    is_locked: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    reason: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    risk_score: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    locked_by: Mapped[Optional[uuid.UUID]] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    locked_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    unlocked_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    user: Mapped["User"] = relationship(foreign_keys=[user_id], lazy="selectin")  # noqa: F821

    def __repr__(self) -> str:
        return f"<AccountLock user_id={self.user_id} is_locked={self.is_locked}>"


# ---------------------------------------------------------------------------
# FraudFlag
# ---------------------------------------------------------------------------
class FraudFlag(BaseModel):
    """Anti-cheat flag raised against a user (optionally tied to an entity
    such as a team, match, or tournament). Deduplicated so the same
    detector never creates duplicate open flags for the same subject."""

    __tablename__ = "fraud_flags"
    __table_args__ = (
        UniqueConstraint(
            "user_id", "flag_type", "related_entity_type", "related_entity_id",
            name="uq_fraud_flags_user_type_entity",
        ),
        Index("ix_fraud_flags_status", "status"),
        Index("ix_fraud_flags_type", "flag_type"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    flag_type: Mapped[FraudFlagType] = mapped_column(str_enum(FraudFlagType, "fraud_flag_type"), nullable=False)
    status: Mapped[FraudFlagStatus] = mapped_column(
        str_enum(FraudFlagStatus, "fraud_flag_status"), nullable=False, default=FraudFlagStatus.OPEN
    )
    risk_score: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    related_entity_type: Mapped[str] = mapped_column(String(50), nullable=False, default="none")
    related_entity_id: Mapped[str] = mapped_column(String(100), nullable=False, default="")

    details: Mapped[Optional[dict]] = mapped_column(PortableJSONB, nullable=True)
    description: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)

    reviewed_by: Mapped[Optional[uuid.UUID]] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    reviewed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    review_notes: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)

    user: Mapped["User"] = relationship(foreign_keys=[user_id], lazy="selectin")  # noqa: F821

    def __repr__(self) -> str:
        return f"<FraudFlag id={self.id} type={self.flag_type} status={self.status}>"


# ---------------------------------------------------------------------------
# AnalyticsSnapshot
# ---------------------------------------------------------------------------
class AnalyticsSnapshot(BaseModel):
    """Cached aggregate metrics for a given metric type + period, so
    repeated dashboard/analytics reads don't recompute expensive
    aggregations. Deduplicated per (metric_type, period_type, period_start)."""

    __tablename__ = "analytics_snapshots"
    __table_args__ = (
        UniqueConstraint(
            "metric_type", "period_type", "period_start",
            name="uq_analytics_snapshots_metric_period",
        ),
        Index("ix_analytics_snapshots_period", "period_type", "period_start"),
    )

    metric_type: Mapped[AnalyticsMetricType] = mapped_column(
        str_enum(AnalyticsMetricType, "analytics_metric_type"), nullable=False
    )
    period_type: Mapped[AnalyticsPeriodType] = mapped_column(
        str_enum(AnalyticsPeriodType, "analytics_period_type"), nullable=False
    )
    period_start: Mapped[date] = mapped_column(Date, nullable=False)
    period_end: Mapped[date] = mapped_column(Date, nullable=False)

    data: Mapped[dict] = mapped_column(PortableJSONB, nullable=False)

    def __repr__(self) -> str:
        return (
            f"<AnalyticsSnapshot metric={self.metric_type} period={self.period_type} "
            f"start={self.period_start}>"
        )
