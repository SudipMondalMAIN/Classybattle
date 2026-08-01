"""
Room Management & Match Lifecycle API routes (Phase 7).
"""
import math
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.session import get_db_session
from app.dependencies.auth import get_current_active_verified_user
from app.models.match import MatchStatus
from app.models.match_participant import MatchAssignmentType
from app.models.user import User
from app.schemas.match import (
    AssignParticipantRequest,
    AssignTeamRequest,
    AutoAssignMatchRequest,
    CheckInRequest,
    MatchCreate,
    MatchParticipantRead,
    MatchRead,
    MatchReadWithSlots,
    MatchResultUpdate,
    MatchRoomRead,
    MatchSchedule,
    MatchStatusUpdate,
    MatchUpdate,
    NoShowOverride,
    OrganizerCheckInOverride,
    PaginatedMatches,
    ReplaceSlotRequest,
    RoomCreate,
    RoomUpdate,
)
from app.services.match_service import MatchService

router = APIRouter(tags=["Match & Room Management"])


def _paginate(items, total, page, page_size) -> PaginatedMatches:
    total_pages = math.ceil(total / page_size) if total else 0
    return PaginatedMatches(
        items=[MatchRead.model_validate(m) for m in items],
        total=total,
        page=page,
        page_size=page_size,
        total_pages=total_pages,
    )


# ----------------------------------------------------------------------
# 8/9. Match CRUD — organizer create/manage, public view
# ----------------------------------------------------------------------
@router.post(
    "/tournaments/{tournament_id}/matches",
    response_model=MatchRead,
    status_code=201,
)
async def create_match(
    tournament_id: UUID,
    payload: MatchCreate,
    current_user: User = Depends(get_current_active_verified_user),
    session: AsyncSession = Depends(get_db_session),
):
    service = MatchService(session)
    match = await service.create_match(tournament_id, payload, current_user)
    return MatchRead.model_validate(match)


@router.get("/tournaments/{tournament_id}/matches", response_model=PaginatedMatches)
async def list_tournament_matches(
    tournament_id: UUID,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    round_number: Optional[int] = Query(None, gt=0),
    match_status: Optional[MatchStatus] = Query(None),
    sort_by: str = Query("round_number"),
    sort_order: str = Query("asc", pattern="^(?i)(asc|desc)$"),
    session: AsyncSession = Depends(get_db_session),
):
    service = MatchService(session)
    items, total = await service.list_matches_public(
        tournament_id,
        page=page,
        page_size=page_size,
        round_number=round_number,
        match_status=match_status,
        sort_by=sort_by,
        sort_order=sort_order,
    )
    return _paginate(items, total, page, page_size)


@router.get("/tournaments/{tournament_id}/matches/manage", response_model=PaginatedMatches)
async def list_tournament_matches_organizer(
    tournament_id: UUID,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    round_number: Optional[int] = Query(None, gt=0),
    match_status: Optional[MatchStatus] = Query(None),
    sort_by: str = Query("round_number"),
    sort_order: str = Query("asc", pattern="^(?i)(asc|desc)$"),
    current_user: User = Depends(get_current_active_verified_user),
    session: AsyncSession = Depends(get_db_session),
):
    service = MatchService(session)
    items, total = await service.list_matches_organizer(
        tournament_id,
        current_user,
        page=page,
        page_size=page_size,
        round_number=round_number,
        match_status=match_status,
        sort_by=sort_by,
        sort_order=sort_order,
    )
    return _paginate(items, total, page, page_size)


@router.get("/matches/{match_id}", response_model=MatchReadWithSlots)
async def get_match(
    match_id: UUID,
    session: AsyncSession = Depends(get_db_session),
):
    service = MatchService(session)
    match = await service.get_match(match_id)
    slots = await service.list_match_slots(match_id)
    data = MatchReadWithSlots.model_validate(match)
    data.slots = [MatchParticipantRead.model_validate(s) for s in slots]
    return data


@router.patch("/matches/{match_id}", response_model=MatchRead)
async def update_match(
    match_id: UUID,
    payload: MatchUpdate,
    current_user: User = Depends(get_current_active_verified_user),
    session: AsyncSession = Depends(get_db_session),
):
    service = MatchService(session)
    match = await service.update_match(match_id, payload, current_user)
    return MatchRead.model_validate(match)


@router.delete("/matches/{match_id}", status_code=204)
async def remove_match(
    match_id: UUID,
    current_user: User = Depends(get_current_active_verified_user),
    session: AsyncSession = Depends(get_db_session),
):
    service = MatchService(session)
    await service.remove_match(match_id, current_user)


# ----------------------------------------------------------------------
# 4. Match Schedule
# ----------------------------------------------------------------------
@router.post("/matches/{match_id}/schedule", response_model=MatchRead)
async def schedule_match(
    match_id: UUID,
    payload: MatchSchedule,
    current_user: User = Depends(get_current_active_verified_user),
    session: AsyncSession = Depends(get_db_session),
):
    service = MatchService(session)
    match = await service.schedule_match(match_id, payload, current_user)
    return MatchRead.model_validate(match)


@router.post("/matches/{match_id}/reschedule", response_model=MatchRead)
async def reschedule_match(
    match_id: UUID,
    payload: MatchSchedule,
    current_user: User = Depends(get_current_active_verified_user),
    session: AsyncSession = Depends(get_db_session),
):
    service = MatchService(session)
    match = await service.reschedule_match(match_id, payload, current_user)
    return MatchRead.model_validate(match)


# ----------------------------------------------------------------------
# 5. Match Status
# ----------------------------------------------------------------------
@router.patch("/matches/{match_id}/status", response_model=MatchRead)
async def update_match_status(
    match_id: UUID,
    payload: MatchStatusUpdate,
    current_user: User = Depends(get_current_active_verified_user),
    session: AsyncSession = Depends(get_db_session),
):
    service = MatchService(session)
    match = await service.update_match_status(match_id, payload.match_status, current_user)
    return MatchRead.model_validate(match)


@router.patch("/matches/{match_id}/result", response_model=MatchRead)
async def update_match_result(
    match_id: UUID,
    payload: MatchResultUpdate,
    current_user: User = Depends(get_current_active_verified_user),
    session: AsyncSession = Depends(get_db_session),
):
    service = MatchService(session)
    match = await service.update_match_result(match_id, payload, current_user)
    return MatchRead.model_validate(match)


# ----------------------------------------------------------------------
# 3. Room Management
# ----------------------------------------------------------------------
@router.post("/matches/{match_id}/room", response_model=MatchRoomRead, status_code=201)
async def create_room(
    match_id: UUID,
    payload: RoomCreate,
    current_user: User = Depends(get_current_active_verified_user),
    session: AsyncSession = Depends(get_db_session),
):
    service = MatchService(session)
    match = await service.create_room(match_id, payload, current_user)
    return MatchRoomRead.model_validate(match)


@router.patch("/matches/{match_id}/room", response_model=MatchRoomRead)
async def update_room(
    match_id: UUID,
    payload: RoomUpdate,
    current_user: User = Depends(get_current_active_verified_user),
    session: AsyncSession = Depends(get_db_session),
):
    service = MatchService(session)
    match = await service.update_room(match_id, payload, current_user)
    return MatchRoomRead.model_validate(match)


@router.post("/matches/{match_id}/room/publish", response_model=MatchRoomRead)
async def publish_room(
    match_id: UUID,
    current_user: User = Depends(get_current_active_verified_user),
    session: AsyncSession = Depends(get_db_session),
):
    service = MatchService(session)
    match = await service.publish_room(match_id, current_user)
    return MatchRoomRead.model_validate(match)


@router.post("/matches/{match_id}/room/hide", response_model=MatchRoomRead)
async def hide_room(
    match_id: UUID,
    current_user: User = Depends(get_current_active_verified_user),
    session: AsyncSession = Depends(get_db_session),
):
    service = MatchService(session)
    match = await service.hide_room(match_id, current_user)
    return MatchRoomRead.model_validate(match)


@router.delete("/matches/{match_id}/room", response_model=MatchRoomRead)
async def delete_room(
    match_id: UUID,
    current_user: User = Depends(get_current_active_verified_user),
    session: AsyncSession = Depends(get_db_session),
):
    service = MatchService(session)
    match = await service.delete_room(match_id, current_user)
    return MatchRoomRead.model_validate(match)


@router.get("/matches/{match_id}/room", response_model=MatchRoomRead)
async def get_match_room(
    match_id: UUID,
    current_user: User = Depends(get_current_active_verified_user),
    session: AsyncSession = Depends(get_db_session),
):
    """Room credentials are only included once published, and only for an
    organizer/admin or a player/captain assigned to this match."""
    service = MatchService(session)
    match = await service.get_match_room(match_id, current_user)
    return MatchRoomRead.model_validate(match)


# ----------------------------------------------------------------------
# 2. Match Team / Player Assignment
# ----------------------------------------------------------------------
@router.post(
    "/matches/{match_id}/assign/team",
    response_model=MatchParticipantRead,
    status_code=201,
)
async def assign_team(
    match_id: UUID,
    payload: AssignTeamRequest,
    current_user: User = Depends(get_current_active_verified_user),
    session: AsyncSession = Depends(get_db_session),
):
    service = MatchService(session)
    slot = await service.assign_team(
        match_id,
        payload.team_id,
        current_user,
        slot_number=payload.slot_number,
        assignment_type=MatchAssignmentType.MANUAL,
    )
    return MatchParticipantRead.model_validate(slot)


@router.post(
    "/matches/{match_id}/assign/participant",
    response_model=MatchParticipantRead,
    status_code=201,
)
async def assign_participant(
    match_id: UUID,
    payload: AssignParticipantRequest,
    current_user: User = Depends(get_current_active_verified_user),
    session: AsyncSession = Depends(get_db_session),
):
    service = MatchService(session)
    slot = await service.assign_participant(
        match_id,
        payload.participant_id,
        current_user,
        slot_number=payload.slot_number,
        assignment_type=MatchAssignmentType.MANUAL,
    )
    return MatchParticipantRead.model_validate(slot)


@router.post(
    "/matches/{match_id}/assign/auto",
    response_model=list[MatchParticipantRead],
    status_code=201,
)
async def auto_assign_match(
    match_id: UUID,
    payload: AutoAssignMatchRequest,
    current_user: User = Depends(get_current_active_verified_user),
    session: AsyncSession = Depends(get_db_session),
):
    service = MatchService(session)
    slots = await service.auto_assign(match_id, current_user, seed=payload.seed)
    return [MatchParticipantRead.model_validate(s) for s in slots]


@router.post("/matches/{match_id}/slots/{slot_id}/replace", response_model=MatchParticipantRead)
async def replace_slot(
    match_id: UUID,
    slot_id: UUID,
    payload: ReplaceSlotRequest,
    current_user: User = Depends(get_current_active_verified_user),
    session: AsyncSession = Depends(get_db_session),
):
    service = MatchService(session)
    slot = await service.replace_slot(
        match_id,
        slot_id,
        current_user,
        new_team_id=payload.new_team_id,
        new_participant_id=payload.new_participant_id,
    )
    return MatchParticipantRead.model_validate(slot)


@router.delete("/matches/{match_id}/slots/{slot_id}", status_code=204)
async def unassign_slot(
    match_id: UUID,
    slot_id: UUID,
    current_user: User = Depends(get_current_active_verified_user),
    session: AsyncSession = Depends(get_db_session),
):
    service = MatchService(session)
    await service.unassign_slot(match_id, slot_id, current_user)


@router.get("/matches/{match_id}/slots", response_model=list[MatchParticipantRead])
async def list_match_slots(
    match_id: UUID,
    session: AsyncSession = Depends(get_db_session),
):
    service = MatchService(session)
    slots = await service.list_match_slots(match_id)
    return [MatchParticipantRead.model_validate(s) for s in slots]


# ----------------------------------------------------------------------
# 6. Check-in System
# ----------------------------------------------------------------------
@router.post("/matches/{match_id}/check-in", response_model=MatchParticipantRead)
async def check_in(
    match_id: UUID,
    payload: CheckInRequest,
    current_user: User = Depends(get_current_active_verified_user),
    session: AsyncSession = Depends(get_db_session),
):
    service = MatchService(session)
    slot = await service.check_in(
        match_id,
        current_user,
        team_id=payload.team_id,
        participant_id=payload.participant_id,
    )
    return MatchParticipantRead.model_validate(slot)


@router.post("/matches/{match_id}/check-in/override", response_model=MatchParticipantRead)
async def organizer_override_check_in(
    match_id: UUID,
    payload: OrganizerCheckInOverride,
    current_user: User = Depends(get_current_active_verified_user),
    session: AsyncSession = Depends(get_db_session),
):
    service = MatchService(session)
    slot = await service.organizer_override_check_in(
        match_id, payload.slot_id, payload.check_in_status, current_user
    )
    return MatchParticipantRead.model_validate(slot)


@router.get("/matches/{match_id}/check-in", response_model=list[MatchParticipantRead])
async def get_check_in_status(
    match_id: UUID,
    session: AsyncSession = Depends(get_db_session),
):
    service = MatchService(session)
    slots = await service.get_check_in_status(match_id)
    return [MatchParticipantRead.model_validate(s) for s in slots]


# ----------------------------------------------------------------------
# 7. No-show Handling
# ----------------------------------------------------------------------
@router.post("/matches/{match_id}/no-show", response_model=MatchParticipantRead)
async def mark_no_show(
    match_id: UUID,
    payload: NoShowOverride,
    current_user: User = Depends(get_current_active_verified_user),
    session: AsyncSession = Depends(get_db_session),
):
    service = MatchService(session)
    slot = await service.mark_no_show(
        match_id, payload.slot_id, current_user, disqualify=payload.is_disqualified
    )
    return MatchParticipantRead.model_validate(slot)


@router.post("/matches/{match_id}/no-show/override", response_model=MatchParticipantRead)
async def override_no_show(
    match_id: UUID,
    payload: NoShowOverride,
    current_user: User = Depends(get_current_active_verified_user),
    session: AsyncSession = Depends(get_db_session),
):
    service = MatchService(session)
    slot = await service.override_no_show(
        match_id,
        payload.slot_id,
        current_user,
        is_disqualified=payload.is_disqualified,
        reason=payload.reason,
    )
    return MatchParticipantRead.model_validate(slot)
