"""
OTP model — used for both signup verification and password reset.
"""
import enum
from datetime import datetime

from typing import Optional

from sqlalchemy import Boolean, DateTime, Enum, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import BaseModel
from app.database.types import PortableJSONB, str_enum


class OTPPurpose(str, enum.Enum):
    SIGNUP_VERIFICATION = "signup_verification"
    PASSWORD_RESET = "password_reset"


class OTP(BaseModel):
    __tablename__ = "otps"

    email: Mapped[str] = mapped_column(String(255), index=True, nullable=False)
    otp_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    purpose: Mapped[OTPPurpose] = mapped_column(str_enum(OTPPurpose, "otp_purpose"), nullable=False)

    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    is_used: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # Holds the not-yet-persisted signup details (full_name, phone_number,
    # hashed_password) while the account awaits OTP verification. Only used
    # for OTPPurpose.SIGNUP_VERIFICATION; null for password-reset OTPs.
    # The User row is created only after this OTP is successfully verified,
    # so no user data reaches the `users` table until the email is confirmed.
    signup_payload: Mapped[Optional[dict]] = mapped_column(PortableJSONB, nullable=True)

    def __repr__(self) -> str:
        return f"<OTP id={self.id} email={self.email} purpose={self.purpose}>"