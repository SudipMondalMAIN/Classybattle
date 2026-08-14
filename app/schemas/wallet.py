"""
Wallet & Wallet Transaction Pydantic schemas — Phase 8 (Enterprise Wallet System).
"""
from datetime import datetime
from decimal import Decimal
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.wallet_transaction import WalletTransactionStatus, WalletTransactionType


# ----------------------------------------------------------------------
# Wallet
# ----------------------------------------------------------------------
class WalletRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    user_id: UUID
    available_balance: Decimal
    locked_balance: Decimal
    currency: str
    is_frozen: bool
    created_at: datetime
    updated_at: datetime


class WalletReadWithTotal(WalletRead):
    total_balance: Decimal


# ----------------------------------------------------------------------
# Wallet Transaction
# ----------------------------------------------------------------------
class WalletTransactionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    wallet_id: UUID
    user_id: UUID
    type: WalletTransactionType
    status: WalletTransactionStatus
    amount: Decimal
    currency: str
    available_balance_after: Decimal
    locked_balance_after: Decimal
    description: Optional[str] = None
    reference_type: Optional[str] = None
    reference_id: Optional[str] = None
    related_transaction_id: Optional[UUID] = None
    performed_by_id: Optional[UUID] = None
    created_at: datetime
    # Human-facing 10-digit transaction number — only populated for
    # deposit (reference_type=payment_deposit) and withdrawal
    # (reference_type=withdrawal_request) rows, pulled from the linked
    # PaymentRequest/WithdrawalRequest.txn_no. None for every other
    # transaction type (tournament entry, prize payout, etc.) since
    # those don't have one.
    txn_no: Optional[str] = None


class PaginatedWalletTransactions(BaseModel):
    items: list[WalletTransactionRead]
    total: int
    page: int
    page_size: int
    total_pages: int


# ----------------------------------------------------------------------
# User-facing mutation requests
# ----------------------------------------------------------------------
class WalletHoldRequest(BaseModel):
    amount: Decimal = Field(..., gt=0, decimal_places=2)
    reference_type: str = Field(..., min_length=2, max_length=100)
    reference_id: str = Field(..., min_length=1, max_length=100)
    description: Optional[str] = Field(None, max_length=500)

    @field_validator("amount")
    @classmethod
    def _amount_positive(cls, v: Decimal) -> Decimal:
        if v <= 0:
            raise ValueError("amount must be greater than zero")
        return v


class WalletReleaseHoldRequest(BaseModel):
    hold_transaction_id: UUID
    description: Optional[str] = Field(None, max_length=500)


# ----------------------------------------------------------------------
# Admin mutation requests
# ----------------------------------------------------------------------
class AdminWalletAdjustmentRequest(BaseModel):
    """Positive amount credits the user's wallet, negative amount debits it."""

    amount: Decimal = Field(..., decimal_places=2)
    reason: str = Field(..., min_length=3, max_length=500)

    @field_validator("amount")
    @classmethod
    def _amount_nonzero(cls, v: Decimal) -> Decimal:
        if v == 0:
            raise ValueError("amount must not be zero")
        return v


class AdminWalletCreditRequest(BaseModel):
    amount: Decimal = Field(..., gt=0, decimal_places=2)
    reason: str = Field(..., min_length=3, max_length=500)
    reference_type: Optional[str] = Field(None, max_length=100)
    reference_id: Optional[str] = Field(None, max_length=100)


class AdminWalletDebitRequest(BaseModel):
    amount: Decimal = Field(..., gt=0, decimal_places=2)
    reason: str = Field(..., min_length=3, max_length=500)
    reference_type: Optional[str] = Field(None, max_length=100)
    reference_id: Optional[str] = Field(None, max_length=100)


class AdminWalletFreezeRequest(BaseModel):
    is_frozen: bool
    reason: str = Field(..., min_length=3, max_length=500)


class WalletTransactionFilterParams(BaseModel):
    type: Optional[WalletTransactionType] = None
    status: Optional[WalletTransactionStatus] = None
    date_from: Optional[datetime] = None
    date_to: Optional[datetime] = None