"""
Withdrawal Request schemas.
"""
from datetime import datetime
from decimal import Decimal
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.models.payment_method import PaymentMethodType
from app.models.withdrawal import WithdrawalStatus
from app.schemas.user import UserPublic


class WithdrawalRequestCreate(BaseModel):
    payment_method_id: UUID
    amount: Decimal = Field(..., gt=0)


class WithdrawalRequestRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    short_id: int
    txn_no: str
    user_id: UUID
    amount: Decimal
    currency: str
    method_type: PaymentMethodType
    method_details: dict
    status: WithdrawalStatus
    admin_note: Optional[str] = None
    processed_at: Optional[datetime] = None
    created_at: datetime
    user: Optional[UserPublic] = None


class PaginatedWithdrawalRequests(BaseModel):
    items: list[WithdrawalRequestRead]
    total: int
    page: int
    page_size: int
    total_pages: int


class WithdrawalCompleteRequest(BaseModel):
    admin_note: Optional[str] = Field(None, max_length=500)


class WithdrawalCancelRequest(BaseModel):
    admin_note: Optional[str] = Field(None, max_length=500)