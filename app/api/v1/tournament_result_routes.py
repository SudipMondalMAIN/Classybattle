"""
Tournament Result routes — formerly match_result_routes.py.

Exposes the submit -> verify -> approve / reject workflow for a
Tournament's formal result record.
"""
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.session import get_db_session
from app.dependencies.auth import get_current_active_verified_user, require_admin
from app.models.user import User
from app.schemas.tournament_result import (
    RejectResultRequest,
    SubmitResultRequest,
    TournamentResultRead,
)
from app.services.tournament_result_service import TournamentResultService

router = APIRouter(prefix="/tournaments/{tournament_id}/result", tags=["Tournament Result"])


@router.post("", response_model=TournamentResultRead)
async def submit_tournament_result(
    tournament_id: UUID,
    payload: SubmitResultRequest,
    current_user: User = Depends(get_current_active_verified_user),
    session: AsyncSession = Depends(get_db_session),
):
    service = TournamentResultService(session)
    return await service.submit_result(
        tournament_id,
        result_data=payload.result_data,
        is_tie=payload.is_tie,
        current_user=current_user,
    )


@router.get("", response_model=TournamentResultRead)
async def get_tournament_result(
    tournament_id: UUID,
    session: AsyncSession = Depends(get_db_session),
):
    service = TournamentResultService(session)
    result = await service.get_result(tournament_id)
    if result is None:
        from app.core.exceptions import NotFoundException

        raise NotFoundException("No result submitted for this tournament yet")
    return result


@router.post("/verify", response_model=TournamentResultRead)
async def verify_tournament_result(
    tournament_id: UUID,
    admin: User = Depends(require_admin),
    session: AsyncSession = Depends(get_db_session),
):
    service = TournamentResultService(session)
    result = await service.get_result(tournament_id)
    if result is None:
        from app.core.exceptions import NotFoundException

        raise NotFoundException("No result submitted for this tournament yet")
    return await service.verify_result(result.id, admin)


@router.post("/approve", response_model=TournamentResultRead)
async def approve_tournament_result(
    tournament_id: UUID,
    admin: User = Depends(require_admin),
    session: AsyncSession = Depends(get_db_session),
):
    service = TournamentResultService(session)
    result = await service.get_result(tournament_id)
    if result is None:
        from app.core.exceptions import NotFoundException

        raise NotFoundException("No result submitted for this tournament yet")
    return await service.approve_result(result.id, admin)


@router.post("/reject", response_model=TournamentResultRead)
async def reject_tournament_result(
    tournament_id: UUID,
    payload: RejectResultRequest,
    admin: User = Depends(require_admin),
    session: AsyncSession = Depends(get_db_session),
):
    service = TournamentResultService(session)
    result = await service.get_result(tournament_id)
    if result is None:
        from app.core.exceptions import NotFoundException

        raise NotFoundException("No result submitted for this tournament yet")
    return await service.reject_result(result.id, reason=payload.reason, current_user=admin)
