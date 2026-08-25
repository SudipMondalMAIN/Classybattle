"""
User profile API routes.
"""
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.cache import cache_delete, cache_get, cache_set
from app.database.session import get_db_session
from app.dependencies.auth import get_current_user
from app.models.user import User
from app.schemas.user import UserProfileUpdate, UserRead
from app.services.user_service import UserService

router = APIRouter(prefix="/users", tags=["Users"])

# NOTE: get_current_user (the auth dependency) still hits the DB on every
# request to load + validate the token's user -- that's unavoidable here,
# it's what actually authenticates the request. What we cache below is the
# *serialized profile payload* this endpoint returns, so a client that
# polls GET /me repeatedly (common right after login / on app resume)
# doesn't force the extra profile serialization/relationship access each
# time. Profile fields rarely change, so cache for an hour;
# update_my_profile invalidates immediately regardless of TTL.
_PROFILE_CACHE_TTL = 3600


def _profile_cache_key(user_id) -> str:
    return f"user:profile:{user_id}"


@router.get("/me", response_model=UserRead)
async def get_my_profile(current_user: User = Depends(get_current_user)):
    cache_key = _profile_cache_key(current_user.id)
    cached = await cache_get(cache_key)
    if cached is not None:
        return UserRead.model_validate(cached)

    result = UserRead.model_validate(current_user)
    await cache_set(cache_key, result.model_dump(mode="json"), ttl=_PROFILE_CACHE_TTL)
    return result


@router.patch("/me", response_model=UserRead)
async def update_my_profile(
    payload: UserProfileUpdate,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
):
    service = UserService(session)
    updated_user = await service.update_profile(current_user.id, payload)
    await cache_delete(_profile_cache_key(current_user.id))
    return UserRead.model_validate(updated_user)
