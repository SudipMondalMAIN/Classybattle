"""
App version / force-update routes.

Public: GET /app/version/check -- hit by the Flutter splash screen.
Admin:  GET/PUT /app/version/{platform} -- manage the config, no redeploy needed.
"""
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.session import get_db_session
from app.dependencies.auth import require_admin
from app.models.app_version import AppPlatform
from app.models.user import User
from app.schemas.app_version import (
    AppVersionCheckResponse,
    AppVersionRead,
    AppVersionUpsert,
    MaintenanceModeToggle,
)
from app.services.app_version_service import AppVersionService

router = APIRouter(prefix="/app/version", tags=["App Version"])


@router.get("/check", response_model=AppVersionCheckResponse)
async def check_app_version(
    platform: AppPlatform = Query(...),
    current_version: str = Query(..., max_length=20),
    session: AsyncSession = Depends(get_db_session),
):
    """Called from the splash screen. Tells the app whether to nudge or block."""
    service = AppVersionService(session)
    return await service.check(platform, current_version)


@router.get("/{platform}", response_model=AppVersionRead)
async def get_app_version(
    platform: AppPlatform,
    current_user: User = Depends(require_admin),
    session: AsyncSession = Depends(get_db_session),
):
    service = AppVersionService(session)
    record = await service.get(platform)
    return AppVersionRead.model_validate(record)


@router.put("/{platform}", response_model=AppVersionRead)
async def set_app_version(
    platform: AppPlatform,
    payload: AppVersionUpsert,
    current_user: User = Depends(require_admin),
    session: AsyncSession = Depends(get_db_session),
):
    """Admin sets/updates version info -- this is what triggers the force update."""
    service = AppVersionService(session)
    record = await service.upsert(platform, payload)
    return AppVersionRead.model_validate(record)


@router.post("/{platform}/maintenance", response_model=AppVersionRead)
async def toggle_maintenance_mode(
    platform: AppPlatform,
    payload: MaintenanceModeToggle,
    current_user: User = Depends(require_admin),
    session: AsyncSession = Depends(get_db_session),
):
    """One-tap kill-switch: instantly blocks (or unblocks) every installed
    app on this platform with the maintenance screen, independent of
    version numbers -- no need to fake latest_version/force_update."""
    service = AppVersionService(session)
    record = await service.set_maintenance(
        platform,
        enabled=payload.enabled,
        title=payload.title,
        message=payload.message,
        status_url=payload.status_url,
    )
    return AppVersionRead.model_validate(record)
