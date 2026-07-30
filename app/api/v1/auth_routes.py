"""
Authentication API routes.
"""
from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.settings import settings
from app.database.session import get_db_session
from app.models.otp import OTPPurpose
from app.schemas.auth import (
    AccessTokenResponse,
    ForgotPasswordRequest,
    LoginRequest,
    RefreshTokenRequest,
    ResendOTPRequest,
    ResetPasswordRequest,
    SignupInitResponse,
    SignupRequest,
    TokenResponse,
    VerifyResetOTPRequest,
    VerifySignupOTPRequest,
)
from app.schemas.common import MessageResponse
from app.schemas.user import UserRead
from app.services.auth_service import AuthService

router = APIRouter(prefix="/auth", tags=["Authentication"])


@router.post("/signup", response_model=SignupInitResponse, status_code=status.HTTP_201_CREATED)
async def signup(payload: SignupRequest, session: AsyncSession = Depends(get_db_session)):
    """Step 1 of signup: validate details, create pending account, send OTP."""
    service = AuthService(session)
    await service.initiate_signup(payload)
    return SignupInitResponse(
        message="OTP sent to your email. Please verify to complete signup.",
        email=payload.email,
        otp_expires_in_minutes=settings.OTP_EXPIRY_MINUTES,
    )


@router.post("/signup/verify-otp", response_model=TokenResponse)
async def verify_signup_otp(
    payload: VerifySignupOTPRequest, session: AsyncSession = Depends(get_db_session)
):
    """Step 2 of signup: verify OTP, activate account, return tokens."""
    service = AuthService(session)
    user, access_token, refresh_token = await service.verify_signup_otp(payload.email, payload.otp)
    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        user=UserRead.model_validate(user),
    )


@router.post("/otp/resend", response_model=MessageResponse)
async def resend_otp(payload: ResendOTPRequest, session: AsyncSession = Depends(get_db_session)):
    service = AuthService(session)
    await service.resend_otp(payload.email, OTPPurpose(payload.purpose))
    return MessageResponse(message="OTP resent successfully")


@router.post("/login", response_model=TokenResponse)
async def login(payload: LoginRequest, session: AsyncSession = Depends(get_db_session)):
    service = AuthService(session)
    user, access_token, refresh_token = await service.login(payload)
    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        user=UserRead.model_validate(user),
    )


@router.post("/token/refresh", response_model=AccessTokenResponse)
async def refresh_token(
    payload: RefreshTokenRequest, session: AsyncSession = Depends(get_db_session)
):
    service = AuthService(session)
    access_token = await service.refresh_access_token(payload.refresh_token)
    return AccessTokenResponse(access_token=access_token)


@router.post("/logout", response_model=MessageResponse)
async def logout(payload: RefreshTokenRequest, session: AsyncSession = Depends(get_db_session)):
    service = AuthService(session)
    await service.logout(payload.refresh_token)
    return MessageResponse(message="Logged out successfully")


@router.post("/password/forgot", response_model=MessageResponse)
async def forgot_password(
    payload: ForgotPasswordRequest, session: AsyncSession = Depends(get_db_session)
):
    service = AuthService(session)
    await service.forgot_password(payload.email)
    return MessageResponse(
        message="If an account exists for this email, a password reset OTP has been sent."
    )


@router.post("/password/verify-otp", response_model=MessageResponse)
async def verify_reset_otp(
    payload: VerifyResetOTPRequest, session: AsyncSession = Depends(get_db_session)
):
    service = AuthService(session)
    await service.verify_reset_otp(payload.email, payload.otp)
    return MessageResponse(message="OTP verified. You may now reset your password.")


@router.post("/password/reset", response_model=MessageResponse)
async def reset_password(
    payload: ResetPasswordRequest, session: AsyncSession = Depends(get_db_session)
):
    service = AuthService(session)
    await service.reset_password(payload)
    return MessageResponse(message="Password reset successfully. Please log in again.")
