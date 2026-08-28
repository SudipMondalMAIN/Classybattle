"""
Referral System v2 — request/response schemas.
"""
from datetime import datetime
from decimal import Decimal
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

from app.models.referral import ReferralStatus


# ---------------------------------------------------------------------------
# User-facing
# ---------------------------------------------------------------------------
class MyReferralCodeResponse(BaseModel):
    referral_code: str
    total_referred: int
    completed_referrals: int
    pending_referrals: int
    on_hold_referrals: int
    total_earned: Decimal
    next_milestone_at: Optional[int] = None
    next_milestone_bonus: Optional[Decimal] = None


class ReferralMilestoneRuleOut(BaseModel):
    threshold: int
    bonus: Decimal


class ReferralRulesResponse(BaseModel):
    """Public-facing version of ReferralConfig -- everything the app
    needs to explain "how it works" and "how much you earn" to a user,
    with no admin/fraud-only fields (max_accounts_per_ip,
    fraud_check_enabled) leaked to the client."""
    reward_amount: Decimal
    min_deposit_amount: Decimal
    require_deposit_step: bool
    require_paid_tournament_step: bool
    apply_window_days: int
    milestone_rules: list[ReferralMilestoneRuleOut]


class ApplyReferralCodeRequest(BaseModel):
    referral_code: str = Field(..., min_length=1, max_length=16)
    # Client-supplied device identifier (Flutter installation/device id),
    # used only for the duplicate-device fraud check.
    device_id: Optional[str] = Field(None, max_length=255)

    @field_validator("referral_code")
    @classmethod
    def normalize(cls, v: str) -> str:
        return v.strip().upper()


class ReferralStatusItem(BaseModel):
    id: UUID
    referee_name: str
    status: ReferralStatus
    deposit_met: bool
    tournament_met: bool
    reward_amount: Optional[Decimal] = None
    reward_credited: bool
    created_at: datetime

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# Admin
# ---------------------------------------------------------------------------
class ReferralConfigRead(BaseModel):
    id: UUID
    reward_amount: Decimal
    min_deposit_amount: Decimal
    require_deposit_step: bool
    require_paid_tournament_step: bool
    apply_window_days: int
    fraud_check_enabled: bool
    max_accounts_per_ip: int
    milestone_rules: list[dict]

    model_config = {"from_attributes": True}


class MilestoneRuleInput(BaseModel):
    threshold: int = Field(..., gt=0)
    bonus: Decimal = Field(..., gt=0)


class ReferralConfigUpdate(BaseModel):
    reward_amount: Optional[Decimal] = Field(None, gt=0)
    min_deposit_amount: Optional[Decimal] = Field(None, ge=0)
    require_deposit_step: Optional[bool] = None
    require_paid_tournament_step: Optional[bool] = None
    apply_window_days: Optional[int] = Field(None, gt=0)
    fraud_check_enabled: Optional[bool] = None
    max_accounts_per_ip: Optional[int] = Field(None, gt=0)
    milestone_rules: Optional[list[MilestoneRuleInput]] = None


class AdminReferralListItem(BaseModel):
    id: UUID
    referrer_id: UUID
    referrer_name: str
    referrer_email: str
    referee_id: UUID
    referee_name: str
    referee_email: str
    status: ReferralStatus
    ip_address: Optional[str] = None
    device_id: Optional[str] = None
    deposit_met: bool
    tournament_met: bool
    risk_flagged: bool
    risk_reason: Optional[str] = None
    reward_amount: Optional[Decimal] = None
    created_at: datetime


class ReferralRejectRequest(BaseModel):
    admin_note: Optional[str] = Field(None, max_length=500)
