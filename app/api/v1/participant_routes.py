"""
Tournament Registration & Participants API routes (Phase 5, extended in
Phase 9 with Wallet-backed entry fee payment + idempotent registration).
"""
import math
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.session import get_db_session
from app.dependencies.auth import get_current_active_verified_user, require_admin, require_can_play
from app.models.participant import ParticipantStatus
from app.models.user import User
from app.schemas.participant import (
    PaginatedParticipants,
    PaginatedParticipantsOrganizer,
    ParticipantListItem,
    ParticipantOrganizerView,
    ParticipantRead,
    ParticipantRegister,
    ParticipantStatusUpdate,
)
from app.services.idempotency_service import IdempotencyService
from app.services.participant_service import ParticipantService

router = APIRouter(tags=["Tournament Registration"])


# ----------------------------------------------------------------------
# Registration (participant-facing, scoped to a tournament)
# ----------------------------------------------------------------------
@router.post(
    "/tournaments/{tournament_id}/register",
    response_model=ParticipantRead,
    status_code=201,
)
async def register_for_tournament(
    tournament_id: UUID,
    payload: ParticipantRegister,
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
    current_user: User = Depends(require_can_play),
    session: AsyncSession = Depends(get_db_session),
):
    service = ParticipantService(session)

    if not idempotency_key:
        participant = await service.register(tournament_id, payload, current_user)
        return ParticipantRead.model_validate(participant)

    # Idempotent registration: a client retrying the same request (e.g.
    # after a network timeout) with the same Idempotency-Key gets back the
    # original result instead of double-registering / double-charging.
    idempotency_service = IdempotencyService(session)
    async with idempotency_service.begin(
        scope="tournament.register",
        key=idempotency_key,
        user_id=current_user.id,
        payload={
            "tournament_id": str(tournament_id),
            **payload.model_dump(mode="json"),
        },
    ) as guard:
        if guard.replayed:
            return JSONResponse(
                status_code=guard.response_status_code, content=guard.response_body
            )

        participant = await service.register(tournament_id, payload, current_user)
        result = ParticipantRead.model_validate(participant)
        body = result.model_dump(mode="json")
        await guard.complete(status_code=201, body=body)
        await session.commit()
        return result


@router.post(
    "/tournaments/{tournament_id}/cancel",
    response_model=ParticipantRead,
)
async def cancel_tournament_registration(
    tournament_id: UUID,
    current_user: User = Depends(get_current_active_verified_user),
    session: AsyncSession = Depends(get_db_session),
):
    service = ParticipantService(session)
    participant = await service.cancel_registration(tournament_id, current_user)
    return ParticipantRead.model_validate(participant)


@router.get(
    "/tournaments/{tournament_id}/registration",
    response_model=ParticipantRead,
)
async def get_my_registration(
    tournament_id: UUID,
    current_user: User = Depends(get_current_active_verified_user),
    session: AsyncSession = Depends(get_db_session),
):
    service = ParticipantService(session)
    participant = await service.get_registration(tournament_id, current_user)
    return ParticipantRead.model_validate(participant)


# ----------------------------------------------------------------------
# Public participant listing (per tournament)
# ----------------------------------------------------------------------
@router.get(
    "/tournaments/{tournament_id}/participants",
    response_model=PaginatedParticipants,
)
async def list_tournament_participants(
    tournament_id: UUID,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    status: Optional[ParticipantStatus] = Query(None),
    search: Optional[str] = Query(None, max_length=200),
    sort_by: str = Query("created_at"),
    sort_order: str = Query("desc", pattern="^(?i)(asc|desc)$"),
    session: AsyncSession = Depends(get_db_session),
):
    service = ParticipantService(session)
    items, total = await service.list_participants_public(
        tournament_id,
        page=page,
        page_size=page_size,
        status=status,
        search=search,
        sort_by=sort_by,
        sort_order=sort_order,
    )
    total_pages = math.ceil(total / page_size) if total else 0
    return PaginatedParticipants(
        items=[ParticipantListItem.model_validate(p) for p in items],
        total=total,
        page=page,
        page_size=page_size,
        total_pages=total_pages,
    )


# ----------------------------------------------------------------------
# Organizer / Admin participant management (per tournament)
# ----------------------------------------------------------------------
@router.get(
    "/tournaments/{tournament_id}/participants/manage",
    response_model=PaginatedParticipantsOrganizer,
)
async def list_tournament_participants_organizer(
    tournament_id: UUID,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    status: Optional[ParticipantStatus] = Query(None),
    search: Optional[str] = Query(None, max_length=200),
    sort_by: str = Query("created_at"),
    sort_order: str = Query("desc", pattern="^(?i)(asc|desc)$"),
    current_user: User = Depends(get_current_active_verified_user),
    session: AsyncSession = Depends(get_db_session),
):
    service = ParticipantService(session)
    items, total = await service.list_participants_organizer(
        tournament_id,
        current_user,
        page=page,
        page_size=page_size,
        status=status,
        search=search,
        sort_by=sort_by,
        sort_order=sort_order,
    )
    total_pages = math.ceil(total / page_size) if total else 0
    return PaginatedParticipantsOrganizer(
        items=[ParticipantOrganizerView.model_validate(p) for p in items],
        total=total,
        page=page,
        page_size=page_size,
        total_pages=total_pages,
    )


# ----------------------------------------------------------------------
# Individual participant records
# ----------------------------------------------------------------------
@router.get(
    "/participants/short/{short_id}",
    response_model=ParticipantRead,
)
async def get_participant_by_short_id(
    short_id: int,
    current_user: User = Depends(require_admin),
    session: AsyncSession = Depends(get_db_session),
):
    """Admin lookup by the human-friendly 8-digit short_id."""
    service = ParticipantService(session)
    participant = await service.get_participant_by_short_id(short_id)
    return ParticipantRead.model_validate(participant)


@router.get(
    "/participants/{participant_id}",
    response_model=ParticipantRead,
)
async def get_participant_details(
    participant_id: UUID,
    current_user: User = Depends(get_current_active_verified_user),
    session: AsyncSession = Depends(get_db_session),
):
    service = ParticipantService(session)
    participant = await service.get_participant_authorized(participant_id, current_user)
    return ParticipantRead.model_validate(participant)


@router.post(
    "/participants/{participant_id}/leave",
    response_model=ParticipantRead,
)
async def leave_tournament(
    participant_id: UUID,
    current_user: User = Depends(get_current_active_verified_user),
    session: AsyncSession = Depends(get_db_session),
):
    service = ParticipantService(session)
    participant = await service.leave_tournament(participant_id, current_user)
    return ParticipantRead.model_validate(participant)


@router.patch(
    "/participants/{participant_id}/status",
    response_model=ParticipantRead,
)
async def update_participant_status(
    participant_id: UUID,
    payload: ParticipantStatusUpdate,
    current_user: User = Depends(get_current_active_verified_user),
    session: AsyncSession = Depends(get_db_session),
):
    service = ParticipantService(session)
    participant = await service.update_status(participant_id, payload.status, current_user)
    return ParticipantRead.model_validate(participant)


# ----------------------------------------------------------------------
# User registration history
# ----------------------------------------------------------------------
@router.get(
    "/users/me/registrations",
    response_model=PaginatedParticipants,
)
async def my_registration_history(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    status: Optional[ParticipantStatus] = Query(None),
    sort_by: str = Query("created_at"),
    sort_order: str = Query("desc", pattern="^(?i)(asc|desc)$"),
    current_user: User = Depends(get_current_active_verified_user),
    session: AsyncSession = Depends(get_db_session),
):
    service = ParticipantService(session)
    items, total = await service.registration_history(
        current_user,
        page=page,
        page_size=page_size,
        status=status,
        sort_by=sort_by,
        sort_order=sort_order,
    )
    total_pages = math.ceil(total / page_size) if total else 0
    return PaginatedParticipants(
        items=[ParticipantListItem.model_validate(p) for p in items],
        total=total,
        page=page,
        page_size=page_size,
        total_pages=total_pages,
    )