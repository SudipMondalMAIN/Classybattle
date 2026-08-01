"""
Schemas for Security & Anti-Cheat — Phase 16.
"""
from datetime import datetime
from typing import Any, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.models.security import (
    FraudFlagStatus,
    FraudFlagType,
    SecurityEventSeverity,
    SecurityEventType,
)


class LoginHistoryRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    user_id: Optional[UUID]
    email_attempted: Optional[str]
    success: bool
    failure_reason: Optional[str]
    ip_address: Optional[str]
    user_agent: Optional[str]
    device_id: Optional[str]
    platform: Optional[str]
    is_new_device: bool
    is_new_ip: bool
    is_suspicious: bool
    risk_score: int
    created_at: datetime


class PaginatedLoginHistory(BaseModel):
    items: list[LoginHistoryRead]
    total: int
    page: int
    page_size: int


class SecurityEventRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    user_id: Optional[UUID]
    event_type: SecurityEventType
    severity: SecurityEventSeverity
    description: Optional[str]
    event_metadata: Optional[dict]
    ip_address: Optional[str]
    resolved: bool
    resolved_by: Optional[UUID]
    resolved_at: Optional[datetime]
    created_at: datetime


class PaginatedSecurityEvents(BaseModel):
    items: list[SecurityEventRead]
    total: int
    page: int
    page_size: int


class AccountLockRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    user_id: UUID
    is_locked: bool
    reason: Optional[str]
    risk_score: int
    locked_by: Optional[UUID]
    locked_at: Optional[datetime]
    unlocked_at: Optional[datetime]


class AccountLockRequest(BaseModel):
    reason: str


class AccountUnlockRequest(BaseModel):
    reason: Optional[str] = None


class RiskScoreRead(BaseModel):
    user_id: UUID
    risk_score: int
    is_locked: bool
    recent_failed_logins: int
    known_devices: int
    known_ips: int


class FraudFlagRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    user_id: UUID
    flag_type: FraudFlagType
    status: FraudFlagStatus
    risk_score: int
    related_entity_type: str
    related_entity_id: str
    details: Optional[dict]
    description: Optional[str]
    reviewed_by: Optional[UUID]
    reviewed_at: Optional[datetime]
    review_notes: Optional[str]
    created_at: datetime


class PaginatedFraudFlags(BaseModel):
    items: list[FraudFlagRead]
    total: int
    page: int
    page_size: int


class FraudFlagReviewRequest(BaseModel):
    status: FraudFlagStatus
    review_notes: Optional[str] = None


class AntiCheatScanRequest(BaseModel):
    """Optional scoping for an on-demand anti-cheat scan."""

    tournament_id: Optional[UUID] = None
    user_id: Optional[UUID] = None


class AntiCheatScanResult(BaseModel):
    flags_created: int
    flags_checked: int
    details: list[dict[str, Any]] = []
