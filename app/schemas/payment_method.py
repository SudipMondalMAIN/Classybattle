"""
Payment Method schemas — user's saved UPI/Bank withdrawal destinations.
"""
import re
from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models.payment_method import PaymentMethodType

_IFSC_RE = re.compile(r"^[A-Z]{4}0[A-Z0-9]{6}$")
_UPI_RE = re.compile(r"^[\w.\-]{2,256}@[a-zA-Z]{2,64}$")


class PaymentMethodCreate(BaseModel):
    method_type: PaymentMethodType
    account_holder_name: str = Field(..., min_length=2, max_length=150)

    upi_id: Optional[str] = Field(None, max_length=150)
    account_number: Optional[str] = Field(None, min_length=6, max_length=34)
    ifsc_code: Optional[str] = Field(None, min_length=11, max_length=11)

    @model_validator(mode="after")
    def validate_fields_for_type(self) -> "PaymentMethodCreate":
        if self.method_type == PaymentMethodType.UPI:
            if not self.upi_id:
                raise ValueError("upi_id is required for UPI payment methods")
            if not _UPI_RE.match(self.upi_id):
                raise ValueError("Enter a valid UPI ID (e.g. name@bank)")
            self.account_number = None
            self.ifsc_code = None
        else:
            if not self.account_number or not self.ifsc_code:
                raise ValueError("account_number and ifsc_code are required for bank accounts")
            self.ifsc_code = self.ifsc_code.upper()
            if not _IFSC_RE.match(self.ifsc_code):
                raise ValueError("Enter a valid IFSC code")
            if not self.account_number.isdigit():
                raise ValueError("account_number must contain only digits")
            self.upi_id = None
        return self


class PaymentMethodUpdate(BaseModel):
    """Partial update. If upi_id/account fields are provided, they replace
    the existing values for that method's type — the method_type itself
    cannot be changed (create a new method instead)."""

    account_holder_name: Optional[str] = Field(None, min_length=2, max_length=150)
    upi_id: Optional[str] = Field(None, max_length=150)
    account_number: Optional[str] = Field(None, min_length=6, max_length=34)
    ifsc_code: Optional[str] = Field(None, min_length=11, max_length=11)
    is_active: Optional[bool] = None

    @model_validator(mode="after")
    def normalize(self) -> "PaymentMethodUpdate":
        if self.upi_id is not None and not _UPI_RE.match(self.upi_id):
            raise ValueError("Enter a valid UPI ID (e.g. name@bank)")
        if self.ifsc_code is not None:
            self.ifsc_code = self.ifsc_code.upper()
            if not _IFSC_RE.match(self.ifsc_code):
                raise ValueError("Enter a valid IFSC code")
        if self.account_number is not None and not self.account_number.isdigit():
            raise ValueError("account_number must contain only digits")
        return self


class PaymentMethodRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    method_type: PaymentMethodType
    account_holder_name: str
    upi_id: Optional[str] = None
    account_number: Optional[str] = None
    ifsc_code: Optional[str] = None
    is_active: bool
    created_at: datetime
    updated_at: datetime