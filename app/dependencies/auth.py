"""
FastAPI dependencies for authentication and role-based access control.
"""
from uuid import UUID

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ForbiddenException, UnauthorizedException
from app.core.security import TokenType, decode_token
from app.database.session import get_db_session
from app.models.user import User, UserRole
from app.repositories.user_repository import UserRepository

bearer_scheme = HTTPBearer(auto_error=False)


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    session: AsyncSession = Depends(get_db_session),
) -> User:
    if credentials is None:
        raise UnauthorizedException("Authentication credentials were not provided")

    payload = decode_token(credentials.credentials, expected_type=TokenType.ACCESS)
    user_id = payload.get("sub")

    if user_id is None:
        raise UnauthorizedException("Invalid token payload")

    user_repo = UserRepository(session)
    user = await user_repo.get_by_id(UUID(user_id))

    if user is None or not user.is_active:
        raise UnauthorizedException("User not found or inactive")

    await _touch_presence(session, user.id)

    return user


async def _touch_presence(session: AsyncSession, user_id: UUID) -> None:
    """Marks the user online on the back of any authenticated API call, so
    the client doesn't need a dedicated heartbeat/presence call -- simply
    using the app (any screen that hits the API) keeps them marked online.
    Best-effort: presence tracking must never break the actual request."""
    from app.repositories.social_repository import PlayerProfileRepository

    try:
        await PlayerProfileRepository(session).touch_presence_if_stale(user_id)
    except Exception:
        await session.rollback()


async def get_current_user_optional(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    session: AsyncSession = Depends(get_db_session),
) -> User | None:
    """Same as get_current_user but returns None instead of raising when no/invalid
    credentials are provided -- for endpoints that are publicly viewable but need
    to know the caller's identity to decide what to include in the response."""
    if credentials is None:
        return None
    try:
        payload = decode_token(credentials.credentials, expected_type=TokenType.ACCESS)
        user_id = payload.get("sub")
        if user_id is None:
            return None
        user_repo = UserRepository(session)
        user = await user_repo.get_by_id(UUID(user_id))
        if user is None or not user.is_active:
            return None
        await _touch_presence(session, user.id)
        return user
    except Exception:
        return None


async def get_current_active_verified_user(
    current_user: User = Depends(get_current_user),
) -> User:
    if not current_user.is_email_verified:
        raise UnauthorizedException("Email not verified")
    return current_user


async def get_current_enforced_user(
    current_user: User = Depends(get_current_active_verified_user),
    session: AsyncSession = Depends(get_db_session),
) -> User:
    """Same as get_current_active_verified_user, but first lazily lifts
    any suspension/time-boxed ban whose duration has already expired, so
    `current_user.status` reflects reality even though nothing sweeps
    expired moderation actions in the background. Use this (instead of
    get_current_active_verified_user) as the base for any endpoint that
    needs to check suspension/ban status."""
    from app.services.moderation_service import ModerationService

    return await ModerationService(session).refresh_enforcement_status(current_user)


async def require_not_banned(
    current_user: User = Depends(get_current_enforced_user),
) -> User:
    """Blocks BANNED users. A banned user can still log in and can still
    submit/track appeals, but every other write action (deposits,
    withdrawals, joining tournaments) is off-limits."""
    from app.models.user import UserStatus

    if current_user.status == UserStatus.BANNED:
        raise ForbiddenException(
            "Your account has been banned. You can submit an appeal from your notifications/reports page."
        )
    return current_user


async def require_can_play(
    current_user: User = Depends(get_current_enforced_user),
) -> User:
    """Blocks BANNED users (see require_not_banned) and, additionally,
    SUSPENDED users -- suspension only restricts tournament participation;
    a suspended user can still log in, deposit, and withdraw. Once the
    suspension's duration has elapsed this dependency automatically lets
    them through again (via get_current_enforced_user's lazy refresh)."""
    from app.models.user import UserStatus

    if current_user.status == UserStatus.BANNED:
        raise ForbiddenException(
            "Your account has been banned. You can submit an appeal from your notifications/reports page."
        )
    if current_user.status == UserStatus.SUSPENDED:
        raise ForbiddenException(
            "Your account is suspended and you can't join or play tournaments until the suspension ends."
        )
    return current_user


class RequireRole:
    """Dependency factory enforcing that the current user has one of the given roles."""

    def __init__(self, *allowed_roles: UserRole) -> None:
        self.allowed_roles = allowed_roles

    def __call__(self, current_user: User = Depends(get_current_user)) -> User:
        if current_user.role not in self.allowed_roles:
            raise ForbiddenException("You do not have permission to perform this action")
        return current_user


require_admin = RequireRole(UserRole.ADMIN, UserRole.SUPER_ADMIN)
require_super_admin = RequireRole(UserRole.SUPER_ADMIN)