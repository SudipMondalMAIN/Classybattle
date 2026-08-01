"""
Authentication-related Pydantic schemas.
"""
import re

from pydantic import BaseModel, EmailStr, Field, field_validator

from app.core.password_policy import validate_password_strength
from app.schemas.user import UserRead

PHONE_DIGITS_RE = re.compile(r"\D")


class SignupRequest(BaseModel):
    full_name: str = Field(..., min_length=1, max_length=150)
    email: EmailStr
    phone_number: str = Field(..., min_length=1, max_length=20)
    password: str = Field(..., min_length=1, max_length=128)

    @field_validator("phone_number")
    @classmethod
    def validate_phone(cls, v: str) -> str:
        digits = PHONE_DIGITS_RE.sub("", v)
        # Strip an already-included country code (91) or leading trunk 0,
        # so the user only ever needs to type the plain 10-digit number.
        if len(digits) == 12 and digits.startswith("91"):
            digits = digits[2:]
        elif len(digits) == 11 and digits.startswith("0"):
            digits = digits[1:]
        if len(digits) != 10:
            raise ValueError("Enter a valid 10-digit phone number (no country code needed)")
        return f"+91{digits}"

    @field_validator("password")
    @classmethod
    def validate_password(cls, v: str) -> str:
        validate_password_strength(v)
        return v


class SignupInitResponse(BaseModel):
    message: str
    email: EmailStr
    otp_expires_in_minutes: int


class VerifySignupOTPRequest(BaseModel):
    email: EmailStr
    otp: str = Field(..., min_length=4, max_length=8)


class ResendOTPRequest(BaseModel):
    email: EmailStr
    purpose: str = Field(..., pattern="^(signup_verification|password_reset)$")


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=1)


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    user: UserRead


class RefreshTokenRequest(BaseModel):
    refresh_token: str


class AccessTokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class VerifyResetOTPRequest(BaseModel):
    email: EmailStr
    otp: str = Field(..., min_length=4, max_length=8)


class ResetPasswordRequest(BaseModel):
    email: EmailStr
    otp: str = Field(..., min_length=4, max_length=8)
    new_password: str = Field(..., min_length=1, max_length=128)

    @field_validator("new_password")
    @classmethod
    def validate_password(cls, v: str) -> str:
        validate_password_strength(v)
        return v
