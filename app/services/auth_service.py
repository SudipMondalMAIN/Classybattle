"""
Authentication service — orchestrates signup, login, OTP verification,
token issuance/refresh, and password reset flows.
"""
from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.config.settings import settings
from app.core.exceptions import (
    ConflictException,
    InvalidCredentialsException,
    NotFoundException,
    UnauthorizedException,
)
from app.core.logging import get_logger
from app.core.player_uid import generate_player_uid
from app.core.security import (
    TokenType,
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    verify_password,
)
from app.emails.email_service import email_service
from app.models.otp import OTPPurpose
from app.models.user import User, UserRole
from app.core.request_context import get_client_ip
from app.repositories.refresh_token_repository import RefreshTokenRepository
from app.repositories.user_repository import UserRepository
from app.schemas.auth import LoginRequest, ResetPasswordRequest, SignupRequest
from app.services.otp_service import OTPService
from app.services.security_service import SecurityService

logger = get_logger(__name__)


class AuthService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.user_repo = UserRepository(session)
        self.refresh_token_repo = RefreshTokenRepository(session)
        self.otp_service = OTPService(session)

    async def _generate_unique_player_uid(self) -> str:
        """Generate a player_uid, retrying on the rare collision."""
        for _ in range(10):
            candidate = generate_player_uid()
            if await self.user_repo.get_by_player_uid(candidate) is None:
                return candidate
        raise RuntimeError("Could not generate a unique player UID after 10 attempts")

    # ------------------------------------------------------------------
    # SIGNUP
    # ------------------------------------------------------------------
    async def initiate_signup(self, payload: SignupRequest) -> str:
        """
        Validate uniqueness, create an unverified user record, then
        generate + email a signup OTP. Returns the OTP (for internal use/testing);
        callers should not expose it to the client.
        """
        existing = await self.user_repo.exists_by_email_or_phone(payload.email, payload.phone_number)

        if existing is not None and existing.is_email_verified:
            raise ConflictException("An account with this email or phone number already exists")

        if existing is not None and not existing.is_email_verified:
            # Re-use the unverified placeholder account; update details and resend OTP
            await self.user_repo.update(
                existing,
                full_name=payload.full_name,
                phone_number=payload.phone_number,
                hashed_password=hash_password(payload.password),
            )
        else:
            await self.user_repo.create(
                full_name=payload.full_name,
                email=payload.email.lower(),
                phone_number=payload.phone_number,
                hashed_password=hash_password(payload.password),
                role=UserRole.USER,
                is_email_verified=False,
                is_active=True,
                player_uid=await self._generate_unique_player_uid(),
            )

        await self.session.commit()

        otp_code = await self.otp_service.generate_and_store_otp(
            payload.email, OTPPurpose.SIGNUP_VERIFICATION
        )
        await self.session.commit()

        await email_service.send_signup_otp(
            to_email=payload.email,
            full_name=payload.full_name,
            otp=otp_code,
            expiry_minutes=settings.OTP_EXPIRY_MINUTES,
        )

        return otp_code

    async def verify_signup_otp(self, email: str, otp_code: str) -> tuple[User, str, str]:
        """Verify signup OTP, activate the account, and issue tokens."""
        user = await self.user_repo.get_by_email(email)
        if user is None:
            raise NotFoundException("No pending signup found for this email")

        await self.otp_service.verify_otp(email, OTPPurpose.SIGNUP_VERIFICATION, otp_code)

        user = await self.user_repo.update(user, is_email_verified=True)
        await self.session.commit()

        access_token, refresh_token = await self._issue_tokens(user)
        await self.session.commit()

        logger.info("user_signup_completed", user_id=str(user.id))

        try:
            from app.models.notification import NotificationEventType
            from app.notifications.dispatch_service import NotificationDispatchService

            await NotificationDispatchService(self.session).dispatch(
                user=user,
                event_type=NotificationEventType.USER_REGISTRATION,
                title="Welcome to ClassyBattle!",
                body=f"Hi {user.full_name}, your account has been verified successfully.",
                event_key=f"user_registration:{user.id}",
            )
        except Exception as exc:  # noqa: BLE001 - notifications must never break auth
            logger.warning("registration_notification_failed", user_id=str(user.id), error=str(exc))

        return user, access_token, refresh_token

    async def resend_otp(self, email: str, purpose: OTPPurpose) -> None:
        user = await self.user_repo.get_by_email(email)
        if user is None:
            raise NotFoundException("No account found for this email")

        otp_code = await self.otp_service.generate_and_store_otp(email, purpose)
        await self.session.commit()

        if purpose == OTPPurpose.SIGNUP_VERIFICATION:
            await email_service.send_signup_otp(
                to_email=email,
                full_name=user.full_name,
                otp=otp_code,
                expiry_minutes=settings.OTP_EXPIRY_MINUTES,
            )
        else:
            await email_service.send_password_reset_otp(
                to_email=email,
                full_name=user.full_name,
                otp=otp_code,
                expiry_minutes=settings.OTP_EXPIRY_MINUTES,
            )

    # ------------------------------------------------------------------
    # LOGIN
    # ------------------------------------------------------------------
    async def login(self, payload: LoginRequest) -> tuple[User, str, str]:
        security_service = SecurityService(self.session)
        client_ip = get_client_ip()
        user = await self.user_repo.get_by_email(payload.email)

        if user is None or not verify_password(payload.password, user.hashed_password):
            if user is not None:
                await security_service.record_login_attempt(
                    user=user,
                    email_attempted=payload.email,
                    success=False,
                    failure_reason="invalid_credentials",
                    ip_address=client_ip,
                )
            raise InvalidCredentialsException()

        if not user.is_email_verified:
            raise UnauthorizedException("Please verify your email before logging in")

        if not user.is_active:
            raise UnauthorizedException("This account has been deactivated")

        if await security_service.is_locked(user.id):
            await security_service.record_login_attempt(
                user=user,
                email_attempted=payload.email,
                success=False,
                failure_reason="account_locked",
                ip_address=client_ip,
            )
            raise UnauthorizedException("This account has been locked. Please contact support.")

        access_token, refresh_token = await self._issue_tokens(user)
        await security_service.record_login_attempt(
            user=user, email_attempted=payload.email, success=True, ip_address=client_ip
        )
        await self.session.commit()

        logger.info("user_login", user_id=str(user.id))
        return user, access_token, refresh_token

    # ------------------------------------------------------------------
    # TOKENS
    # ------------------------------------------------------------------
    async def _issue_tokens(self, user: User) -> tuple[str, str]:
        access_token = create_access_token(str(user.id), extra_claims={"role": user.role.value})
        refresh_token = create_refresh_token(str(user.id))

        await self.refresh_token_repo.create(
            user_id=user.id,
            token=refresh_token,
            expires_at=datetime.now(timezone.utc) + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS),
            is_revoked=False,
        )
        return access_token, refresh_token

    async def refresh_access_token(self, refresh_token: str) -> str:
        payload = decode_token(refresh_token, expected_type=TokenType.REFRESH)
        stored_token = await self.refresh_token_repo.get_by_token(refresh_token)

        if stored_token is None or stored_token.is_revoked:
            raise UnauthorizedException("Refresh token has been revoked")

        if stored_token.expires_at.replace(tzinfo=timezone.utc) < datetime.now(timezone.utc):
            raise UnauthorizedException("Refresh token has expired")

        user_id = payload.get("sub")
        user = await self.user_repo.get_by_id(UUID(user_id))
        if user is None or not user.is_active:
            raise UnauthorizedException("User not found or inactive")

        return create_access_token(str(user.id), extra_claims={"role": user.role.value})

    async def logout(self, refresh_token: str) -> None:
        stored_token = await self.refresh_token_repo.get_by_token(refresh_token)
        if stored_token is not None:
            stored_token.is_revoked = True
            await self.session.commit()

    # ------------------------------------------------------------------
    # FORGOT / RESET PASSWORD
    # ------------------------------------------------------------------
    async def forgot_password(self, email: str) -> None:
        user = await self.user_repo.get_by_email(email)
        if user is None:
            # Do not reveal whether the account exists
            logger.info("forgot_password_unknown_email", email=email)
            return

        otp_code = await self.otp_service.generate_and_store_otp(email, OTPPurpose.PASSWORD_RESET)
        await self.session.commit()

        await email_service.send_password_reset_otp(
            to_email=email,
            full_name=user.full_name,
            otp=otp_code,
            expiry_minutes=settings.OTP_EXPIRY_MINUTES,
        )

    async def verify_reset_otp(self, email: str, otp_code: str) -> None:
        """Non-destructive check so the client can confirm the OTP before showing the reset form."""
        await self.otp_service.verify_otp(
            email, OTPPurpose.PASSWORD_RESET, otp_code, mark_used=False
        )
        await self.session.commit()

    async def reset_password(self, payload: ResetPasswordRequest) -> None:
        user = await self.user_repo.get_by_email(payload.email)
        if user is None:
            raise NotFoundException("No account found for this email")

        await self.otp_service.verify_otp(payload.email, OTPPurpose.PASSWORD_RESET, payload.otp)

        await self.user_repo.update(user, hashed_password=hash_password(payload.new_password))
        await self.refresh_token_repo.revoke_all_for_user(user.id)
        await self.session.commit()

        logger.info("password_reset_completed", user_id=str(user.id))
