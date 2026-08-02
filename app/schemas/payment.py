"""
Payment & Financial Operations Pydantic schemas — Phase 17.
"""
from datetime import datetime
from decimal import Decimal
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.payment import (
    PaymentProvider,
    PaymentRejectionReason,
    PaymentRequestStatus,
)


# ----------------------------------------------------------------------
# Payment settings (admin)
# ----------------------------------------------------------------------
class PaymentSettingsRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    upi_id: Optional[str] = None
    merchant_name: str
    payment_note: Optional[str] = None
    is_upi_enabled: bool
    min_deposit_amount: Decimal
    max_deposit_amount: Decimal
    updated_by_id: Optional[UUID] = None
    updated_at: datetime


class PaymentSettingsUpdateRequest(BaseModel):
    """All fields optional — only supplied fields are updated."""

    upi_id: Optional[str] = Field(None, min_length=3, max_length=255)
    merchant_name: Optional[str] = Field(None, min_length=1, max_length=255)
    payment_note: Optional[str] = Field(None, max_length=255)
    is_upi_enabled: Optional[bool] = None
    min_deposit_amount: Optional[Decimal] = Field(None, gt=0, decimal_places=2)
    max_deposit_amount: Optional[Decimal] = Field(None, gt=0, decimal_places=2)

    @field_validator("upi_id")
    @classmethod
    def _upi_id_format(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and "@" not in v:
            raise ValueError("upi_id must be a valid VPA, e.g. name@bank")
        return v


# ----------------------------------------------------------------------
# User deposit flow
# ----------------------------------------------------------------------
class DepositQRRequest(BaseModel):
    amount: Decimal = Field(..., gt=0, decimal_places=2)


class DepositQRResponse(BaseModel):
    upi_id: str
    merchant_name: str
    amount: Decimal
    currency: str = "INR"
    note: Optional[str] = None
    qr_payload: str


class PaymentRequestRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    short_id: int
    user_id: UUID
    provider: PaymentProvider
    amount: Decimal
    currency: str
    upi_id_used: Optional[str] = None
    screenshot_url: str
    utr_number: Optional[str] = None
    status: PaymentRequestStatus
    submitted_at: datetime
    verified_by_id: Optional[UUID] = None
    verified_at: Optional[datetime] = None
    rejection_reason: Optional[PaymentRejectionReason] = None
    rejection_note: Optional[str] = None
    admin_note: Optional[str] = None
    wallet_transaction_id: Optional[UUID] = None
    created_at: datetime


class PaginatedPaymentRequests(BaseModel):
    items: list[PaymentRequestRead]
    total: int
    page: int
    page_size: int
    total_pages: int


# ----------------------------------------------------------------------
# Admin verification
# ----------------------------------------------------------------------
class PaymentApproveRequest(BaseModel):
    admin_note: Optional[str] = Field(None, max_length=500)


class PaymentRejectRequest(BaseModel):
    reason: PaymentRejectionReason
    note: Optional[str] = Field(None, max_length=500)


class PaymentHoldRequest(BaseModel):
    admin_note: Optional[str] = Field(None, max_length=500)


class PaymentCancelRequest(BaseModel):
    reason: Optional[str] = Field(None, max_length=500)
