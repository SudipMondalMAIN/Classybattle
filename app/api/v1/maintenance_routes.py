"""
Maintenance kill-switch routes.

Public: GET /app/maintenance/check -- hit by the Flutter splash screen,
        completely separate from /app/version/check.
Admin:  GET  /admin/maintenance         -- current status.
        POST /admin/maintenance/toggle  -- turn it on/off.

Deliberately its own router/table, not layered onto AppVersion, so
enabling/disabling maintenance can never interact with force-update
config and vice versa.
"""
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.session import get_db_session
from app.dependencies.auth import require_admin
from app.models.user import User
from app.schemas.maintenance import (
    MaintenanceCheckResponse,
    MaintenanceRead,
    MaintenanceUpsert,
)
from app.services.maintenance_service import MaintenanceService

router = APIRouter(tags=["Maintenance"])


@router.get("/app/maintenance/check", response_model=MaintenanceCheckResponse)
async def check_maintenance(
    session: AsyncSession = Depends(get_db_session),
):
    """Called from the splash screen, before/alongside the version check.
    Public -- no auth, so it works even for a user who's never logged in."""
    service = MaintenanceService(session)
    return await service.check()


@router.get("/admin/maintenance", response_model=MaintenanceRead)
async def get_maintenance_status(
    current_user: User = Depends(require_admin),
    session: AsyncSession = Depends(get_db_session),
):
    service = MaintenanceService(session)
    record = await service.get_or_create()
    return MaintenanceRead.model_validate(record)


@router.post("/admin/maintenance/toggle", response_model=MaintenanceRead)
async def toggle_maintenance(
    payload: MaintenanceUpsert,
    current_user: User = Depends(require_admin),
    session: AsyncSession = Depends(get_db_session),
):
    """One-tap kill-switch: instantly blocks (or unblocks) every user,
    on every platform, regardless of installed app version."""
    service = MaintenanceService(session)
    record = await service.upsert(payload)
    return MaintenanceRead.model_validate(record)
