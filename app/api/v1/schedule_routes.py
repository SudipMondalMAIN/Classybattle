"""
Schedule (recurring match template) API routes — admin creates/edits
"which game+mode runs, when" and triggers slot generation; anyone can
browse active schedules and a day's generated slots.
"""
from datetime import date
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.session import get_db_session
from app.dependencies.auth import require_admin
from app.models.user import User
from app.schemas.schedule import (
    GenerateSlotsRequest,
    ScheduleCreate,
    ScheduleRead,
    ScheduleUpdate,
)
from app.schemas.slot_join import SlotRead
from app.services.schedule_service import ScheduleService

router = APIRouter(tags=["Match Schedules"])


@router.post("/schedules", response_model=ScheduleRead, status_code=201)
async def create_schedule(
    payload: ScheduleCreate,
    current_user: User = Depends(require_admin),
    session: AsyncSession = Depends(get_db_session),
):
    """Admin: define a recurring match template, e.g. 'Free Fire Classic',
    10:00 AM - 11:00 PM, every 30 minutes."""
    service = ScheduleService(session)
    schedule = await service.create_schedule(payload, current_user)
    return ScheduleRead.model_validate(schedule)


@router.patch("/schedules/{schedule_id}", response_model=ScheduleRead)
async def update_schedule(
    schedule_id: UUID,
    payload: ScheduleUpdate,
    current_user: User = Depends(require_admin),
    session: AsyncSession = Depends(get_db_session),
):
    service = ScheduleService(session)
    schedule = await service.update_schedule(schedule_id, payload, current_user)
    return ScheduleRead.model_validate(schedule)


@router.get("/schedules", response_model=list[ScheduleRead])
async def list_schedules(
    active_only: bool = Query(True),
    session: AsyncSession = Depends(get_db_session),
):
    """Public: browse available game/mode schedules (e.g. to build the
    'Free Fire' / 'BGMI' tabs on the home screen)."""
    service = ScheduleService(session)
    schedules = await service.list_schedules(active_only=active_only)
    return [ScheduleRead.model_validate(s) for s in schedules]


@router.get("/schedules/{schedule_id}", response_model=ScheduleRead)
async def get_schedule(
    schedule_id: UUID,
    session: AsyncSession = Depends(get_db_session),
):
    service = ScheduleService(session)
    schedule = await service.get_schedule(schedule_id)
    return ScheduleRead.model_validate(schedule)


@router.post("/schedules/{schedule_id}/generate-slots", response_model=list[SlotRead])
async def generate_slots(
    schedule_id: UUID,
    payload: GenerateSlotsRequest,
    current_user: User = Depends(require_admin),
    session: AsyncSession = Depends(get_db_session),
):
    """Admin: stamp out today's (or a given date's) join-able Match slots
    for this schedule. Idempotent — safe to call more than once per day.
    In production this should also run automatically via a daily cron
    hitting this endpoint (or calling SlotGeneratorService directly) for
    every active schedule shortly after midnight."""
    service = ScheduleService(session)
    target_date: Optional[date] = payload.target_date.date() if payload.target_date else None
    slots = await service.generate_slots(schedule_id, target_date)
    return [SlotRead.model_validate(s) for s in slots]


@router.get("/schedules/{schedule_id}/slots", response_model=list[SlotRead])
async def list_slots_for_day(
    schedule_id: UUID,
    for_date: Optional[date] = Query(None, description="Defaults to today (UTC)"),
    session: AsyncSession = Depends(get_db_session),
):
    """Public: 'what Free Fire Classic slots are running today' — this is
    the list a user picks a time from before joining."""
    service = ScheduleService(session)
    slots = await service.list_slots_for_day(schedule_id, for_date)
    return [SlotRead.model_validate(s) for s in slots]
