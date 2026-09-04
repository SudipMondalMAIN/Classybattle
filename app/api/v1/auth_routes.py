"""
Authentication API routes.
"""
from fastapi import APIRouter, Depends, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.settings import settings
from app.database.session import get_db_session
from app.middleware.rate_limiter import limiter
from app.models.otp import OTPPurpose
from app.schemas.auth import (
    AccessTokenResponse,
    ForgotPasswordRequest,
    LoginOTPRequest,
    LoginRequest,
    RefreshTokenRequest,
    ResendOTPRequest,
    ResetPasswordRequest,
    SignupInitResponse,
    SignupRequest,
    TokenResponse,
    VerifyLoginOTPRequest,
    VerifyResetOTPRequest,
    VerifySignupOTPRequest,
)
from app.schemas.common import MessageResponse
from app.schemas.user import UserRead
from app.services.auth_service import AuthService
from app.utils.captcha import verify_captcha

router = APIRouter(prefix="/auth", tags=["Authentication"])


@router.post("/signup", response_model=SignupInitResponse, status_code=status.HTTP_201_CREATED)
@limiter.limit(settings.AUTH_RATE_LIMIT)
async def signup(
    request: Request, payload: SignupRequest, session: AsyncSession = Depends(get_db_session)
):
    """Step 1 of signup: validate details, create pending account, send OTP."""
    await verify_captcha(payload.captcha_token, request.client.host if request.client else None)
    service = AuthService(session)
    await service.initiate_signup(payload)
    return SignupInitResponse(
        message="OTP sent to your email. Please verify to complete signup.",
        email=payload.email,
        otp_expires_in_minutes=settings.OTP_EXPIRY_MINUTES,
    )


@router.post("/signup/verify-otp", response_model=TokenResponse)
@limiter.limit(settings.OTP_RATE_LIMIT)
async def verify_signup_otp(
    request: Request,
    payload: VerifySignupOTPRequest,
    session: AsyncSession = Depends(get_db_session),
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
@limiter.limit(settings.OTP_RATE_LIMIT)
async def resend_otp(
    request: Request, payload: ResendOTPRequest, session: AsyncSession = Depends(get_db_session)
):
    service = AuthService(session)
    await service.resend_otp(payload.email, OTPPurpose(payload.purpose))
    return MessageResponse(message="OTP resent successfully")


@router.post("/login", response_model=TokenResponse)
@limiter.limit(settings.AUTH_RATE_LIMIT)
async def login(
    request: Request, payload: LoginRequest, session: AsyncSession = Depends(get_db_session)
):
    await verify_captcha(payload.captcha_token, request.client.host if request.client else None)
    service = AuthService(session)
    user, access_token, refresh_token = await service.login(payload)
    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        user=UserRead.model_validate(user),
    )


@router.post("/login/otp/request", response_model=MessageResponse)
@limiter.limit(settings.LOGIN_OTP_RATE_LIMIT)
async def request_login_otp(
    request: Request, payload: LoginOTPRequest, session: AsyncSession = Depends(get_db_session)
):
    """Step 1 of OTP login: send a login OTP to this email, capped at
    settings.LOGIN_OTP_RATE_LIMIT (2 per 5 minutes per IP)."""
    service = AuthService(session)
    await service.initiate_login_otp(payload.email)
    return MessageResponse(
        message="If an account exists for this email, a login OTP has been sent."
    )


@router.post("/login/otp/verify", response_model=TokenResponse)
@limiter.limit(settings.LOGIN_OTP_RATE_LIMIT)
async def verify_login_otp(
    request: Request, payload: VerifyLoginOTPRequest, session: AsyncSession = Depends(get_db_session)
):
    """Step 2 of OTP login: verify the OTP and issue tokens."""
    service = AuthService(session)
    user, access_token, refresh_token = await service.verify_login_otp(payload.email, payload.otp)
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
@limiter.limit(settings.AUTH_RATE_LIMIT)
async def forgot_password(
    request: Request,
    payload: ForgotPasswordRequest,
    session: AsyncSession = Depends(get_db_session),
):
    service = AuthService(session)
    await service.forgot_password(payload.email)
    return MessageResponse(
        message="If an account exists for this email, a password reset OTP has been sent."
    )


@router.post("/password/verify-otp", response_model=MessageResponse)
@limiter.limit(settings.OTP_RATE_LIMIT)
async def verify_reset_otp(
    request: Request,
    payload: VerifyResetOTPRequest,
    session: AsyncSession = Depends(get_db_session),
):
    service = AuthService(session)
    await service.verify_reset_otp(payload.email, payload.otp)
    return MessageResponse(message="OTP verified. You may now reset your password.")


@router.post("/password/reset", response_model=MessageResponse)
@limiter.limit(settings.AUTH_RATE_LIMIT)
async def reset_password(
    request: Request, payload: ResetPasswordRequest, session: AsyncSession = Depends(get_db_session)
):
    service = AuthService(session)
    await service.reset_password(payload)
    return MessageResponse(message="Password reset successfully. Please log in again.")
