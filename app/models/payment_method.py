"""
PaymentMethod model — a user's saved withdrawal destination (UPI ID or
Bank Account). Editable at any time; a WithdrawalRequest snapshots the
details used at submission time so later edits never rewrite history.
"""
import enum
import uuid
from typing import Optional

from sqlalchemy import Boolean, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import BaseModel
from app.database.types import str_enum


class PaymentMethodType(str, enum.Enum):
    UPI = "upi"
    BANK_ACCOUNT = "bank_account"


class PaymentMethod(BaseModel):
    __tablename__ = "payment_methods"

    user_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )

    method_type: Mapped[PaymentMethodType] = mapped_column(
        str_enum(PaymentMethodType, "payment_method_type"), nullable=False, index=True
    )

    account_holder_name: Mapped[str] = mapped_column(String(150), nullable=False)

    # UPI fields (nullable — only populated when method_type == UPI)
    upi_id: Mapped[Optional[str]] = mapped_column(String(150), nullable=True)

    # Bank fields (nullable — only populated when method_type == BANK_ACCOUNT)
    account_number: Mapped[Optional[str]] = mapped_column(String(34), nullable=True)
    ifsc_code: Mapped[Optional[str]] = mapped_column(String(11), nullable=True)

    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true", nullable=False)

    user: Mapped["User"] = relationship(lazy="selectin")  # noqa: F821

    def as_snapshot(self) -> dict:
        """A plain dict of the details relevant to this method type, used
        to freeze what a withdrawal request actually paid out to."""
        if self.method_type == PaymentMethodType.UPI:
            return {"upi_id": self.upi_id, "account_holder_name": self.account_holder_name}
        return {
            "account_number": self.account_number,
            "ifsc_code": self.ifsc_code,
            "account_holder_name": self.account_holder_name,
        }

    def __repr__(self) -> str:
        return f"<PaymentMethod id={self.id} user_id={self.user_id} type={self.method_type}>"