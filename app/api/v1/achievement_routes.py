"""
Achievement API routes — Phase 15C (Achievements & Moderation).
"""
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.session import get_db_session
from app.dependencies.auth import get_current_active_verified_user, require_admin
from app.models.user import User
from app.schemas.achievement import (
    AchievementCreate,
    AchievementRead,
    BadgeCreate,
    BadgeRead,
    UserAchievementRead,
)
from app.services.achievement_service import AchievementService

router = APIRouter(tags=["Achievements"])


@router.get("/achievements", response_model=list[AchievementRead])
async def list_achievements(session: AsyncSession = Depends(get_db_session)):
    service = AchievementService(session)
    items = await service.list_achievements()
    return [AchievementRead.model_validate(a) for a in items]


@router.get("/achievements/badges", response_model=list[BadgeRead])
async def list_badges(session: AsyncSession = Depends(get_db_session)):
    service = AchievementService(session)
    items = await service.list_badges()
    return [BadgeRead.model_validate(b) for b in items]


@router.get("/achievements/me", response_model=list[UserAchievementRead])
async def list_my_achievements(
    current_user: User = Depends(get_current_active_verified_user),
    session: AsyncSession = Depends(get_db_session),
):
    service = AchievementService(session)
    items = await service.list_for_user(current_user.id)
    return [UserAchievementRead.model_validate(i) for i in items]


@router.get("/users/{user_id}/achievements", response_model=list[UserAchievementRead])
async def list_user_achievements(
    user_id: UUID,
    session: AsyncSession = Depends(get_db_session),
):
    service = AchievementService(session)
    items = await service.list_for_user(user_id)
    return [UserAchievementRead.model_validate(i) for i in items]


# ----------------------------------------------------------------------
# Admin management
# ----------------------------------------------------------------------
@router.post("/admin/achievements/badges", response_model=BadgeRead, status_code=201)
async def admin_create_badge(
    payload: BadgeCreate,
    admin: User = Depends(require_admin),
    session: AsyncSession = Depends(get_db_session),
):
    service = AchievementService(session)
    badge = await service.create_badge(
        admin=admin, name=payload.name, description=payload.description,
        icon_url=payload.icon_url, tier=payload.tier,
    )
    return BadgeRead.model_validate(badge)


@router.post("/admin/achievements", response_model=AchievementRead, status_code=201)
async def admin_create_achievement(
    payload: AchievementCreate,
    admin: User = Depends(require_admin),
    session: AsyncSession = Depends(get_db_session),
):
    service = AchievementService(session)
    achievement = await service.create_achievement(
        admin=admin,
        code=payload.code,
        name=payload.name,
        description=payload.description,
        badge_id=payload.badge_id,
        trigger_type=payload.trigger_type,
        comparison=payload.comparison,
        threshold=payload.threshold,
    )
    return AchievementRead.model_validate(achievement)
