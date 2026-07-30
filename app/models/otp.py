"""
OTP model — used for both signup verification and password reset.
"""
import enum
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Enum, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import BaseModel


class OTPPurpose(str, enum.Enum):
    SIGNUP_VERIFICATION = "signup_verification"
    PASSWORD_RESET = "password_reset"


class OTP(BaseModel):
    __tablename__ = "otps"

    email: Mapped[str] = mapped_column(String(255), index=True, nullable=False)
    otp_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    purpose: Mapped[OTPPurpose] = mapped_column(Enum(OTPPurpose, name="otp_purpose"), nullable=False)

    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    is_used: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    def __repr__(self) -> str:
        return f"<OTP id={self.id} email={self.email} purpose={self.purpose}>"
