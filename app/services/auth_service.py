"""
Authentication service — orchestrates signup, login, OTP verification,
token issuance/refresh, and password reset flows.
"""
from datetime import datetime, timedelta, timezone
from uuid import UUID
import random

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
from app.repositories.leaderboard_repository import PlayerStatisticsRepository
from app.repositories.refresh_token_repository import RefreshTokenRepository
from app.repositories.user_repository import UserRepository
from app.schemas.auth import LoginRequest, ResetPasswordRequest, SignupRequest
from app.services.otp_service import OTPService
from app.services.security_service import SecurityService
from app.utils.avatars import PREDEFINED_AVATARS

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
        Validate uniqueness and generate + email a signup OTP. No row is
        written to the `users` table at this stage — the submitted details
        are held only inside the OTP record (hashed password included) until
        the user verifies their email. Returns the OTP (for internal
        use/testing); callers should not expose it to the client.
        """
        existing = await self.user_repo.exists_by_email_or_phone(payload.email, payload.phone_number)

        if existing is not None:
            # Any row in `users` at this point is, by construction, already
            # email-verified (see verify_signup_otp), so this is always a
            # genuine duplicate account.
            raise ConflictException("An account with this email or phone number already exists")

        signup_payload = {
            "full_name": payload.full_name,
            "phone_number": payload.phone_number,
            "hashed_password": hash_password(payload.password),
        }

        otp_code = await self.otp_service.generate_and_store_otp(
            payload.email, OTPPurpose.SIGNUP_VERIFICATION, signup_payload=signup_payload
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
        """Verify signup OTP, create the now-confirmed account, and issue tokens."""
        email = email.lower()

        # Already-verified accounts can't re-verify; nothing pending means no OTP exists anyway.
        existing = await self.user_repo.get_by_email(email)
        if existing is not None:
            raise ConflictException("An account with this email or phone number already exists")

        otp_entry = await self.otp_service.verify_otp(email, OTPPurpose.SIGNUP_VERIFICATION, otp_code)

        signup_payload = otp_entry.signup_payload
        if not signup_payload:
            raise NotFoundException("No pending signup found for this email")

        # Re-check uniqueness right before writing, in case another signup
        # for the same email/phone completed verification in the meantime.
        conflict = await self.user_repo.exists_by_email_or_phone(
            email, signup_payload["phone_number"]
        )
        if conflict is not None:
            raise ConflictException("An account with this email or phone number already exists")

        user = await self.user_repo.create(
            full_name=signup_payload["full_name"],
            email=email,
            phone_number=signup_payload["phone_number"],
            hashed_password=signup_payload["hashed_password"],
            role=UserRole.USER,
            is_email_verified=True,
            is_active=True,
            player_uid=await self._generate_unique_player_uid(),
            avatar_id=random.choice(PREDEFINED_AVATARS),
        )

        # Every user needs a PlayerStatistics row from day one, otherwise
        # they're invisible on the leaderboard until their first match/
        # payout event creates one (see LeaderboardService.record_match_completion
        # / record_admin_winner_payout). Zero-score row here fixes that.
        await PlayerStatisticsRepository(self.session).get_or_create(user.id)

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
        email = email.lower()

        if purpose == OTPPurpose.SIGNUP_VERIFICATION:
            # No user row exists yet for a pending signup — the details live
            # only on the most recent (still-active) signup OTP.
            previous_otp = await self.otp_service.repo.get_latest_active(
                email, OTPPurpose.SIGNUP_VERIFICATION
            )
            if previous_otp is None or not previous_otp.signup_payload:
                raise NotFoundException("No pending signup found for this email")

            otp_code = await self.otp_service.generate_and_store_otp(
                email, purpose, signup_payload=previous_otp.signup_payload
            )
            await self.session.commit()

            await email_service.send_signup_otp(
                to_email=email,
                full_name=previous_otp.signup_payload["full_name"],
                otp=otp_code,
                expiry_minutes=settings.OTP_EXPIRY_MINUTES,
            )
        else:
            user = await self.user_repo.get_by_email(email)
            if user is None:
                raise NotFoundException("No account found for this email")

            otp_code = await self.otp_service.generate_and_store_otp(email, purpose)
            await self.session.commit()

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
    # OTP LOGIN
    # ------------------------------------------------------------------
    async def initiate_login_otp(self, email: str) -> None:
        """Step 1 of OTP login: send a LOGIN-purpose OTP if a verified,
        active account exists for this email. Deliberately silent on
        "no such account" (same pattern as forgot_password) so this
        endpoint can't be used to check which emails are registered.
        Locked/deactivated accounts are also silently skipped -- OTP
        login must not become a side-channel that bypasses an account
        lock the password path already enforces.
        """
        email = email.lower()
        user = await self.user_repo.get_by_email(email)
        if user is None or not user.is_email_verified or not user.is_active:
            logger.info("login_otp_skipped", email=email, reason="no_eligible_account")
            return

        security_service = SecurityService(self.session)
        if await security_service.is_locked(user.id):
            logger.info("login_otp_skipped", email=email, reason="account_locked")
            return

        otp_code = await self.otp_service.generate_and_store_otp(email, OTPPurpose.LOGIN)
        await self.session.commit()

        await email_service.send_login_otp(
            to_email=email,
            full_name=user.full_name,
            otp=otp_code,
            expiry_minutes=settings.OTP_EXPIRY_MINUTES,
        )

    async def verify_login_otp(self, email: str, otp_code: str) -> tuple[User, str, str]:
        """Step 2 of OTP login: verify the OTP and issue tokens, same
        end state as a successful password login."""
        email = email.lower()
        security_service = SecurityService(self.session)
        client_ip = get_client_ip()

        user = await self.user_repo.get_by_email(email)
        if user is None:
            raise InvalidCredentialsException()

        if not user.is_email_verified:
            raise UnauthorizedException("Please verify your email before logging in")
        if not user.is_active:
            raise UnauthorizedException("This account has been deactivated")
        if await security_service.is_locked(user.id):
            raise UnauthorizedException("This account has been locked. Please contact support.")

        # Any failure here (wrong/expired/exhausted OTP) raises OTPException
        # and propagates as-is -- no need to duplicate SecurityService's
        # login_attempt bookkeeping, since that's specifically about
        # password brute-forcing, not OTP guessing (which OTPService's
        # own attempts/expiry limits already cover).
        await self.otp_service.verify_otp(email, OTPPurpose.LOGIN, otp_code)

        access_token, refresh_token = await self._issue_tokens(user)
        await security_service.record_login_attempt(
            user=user, email_attempted=email, success=True, ip_address=client_ip
        )
        await self.session.commit()

        logger.info("user_login_otp", user_id=str(user.id))
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