"""
Tournament Admin routes — exposes TournamentAdminService's "tournament
details" admin page: who joined, per-player kills, winner declaration,
and winning-amount wallet payout.

Match-refactor: this replaces the deleted match_admin_routes.py, folded
directly under the /tournaments/{tournament_id}/admin/... prefix instead
of a separate top-level router.
"""
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.session import get_db_session
from app.dependencies.auth import require_admin
from app.models.user import User
from app.schemas.tournament_admin import (
    DeclareResultRequest,
    MatchAdminDetailRead,
    PayWinnerRequest,
    PlayerActionRead,
)
from app.schemas.tournament_result import TournamentResultRead
from app.services.tournament_admin_service import TournamentAdminService

router = APIRouter(prefix="/tournaments/{tournament_id}/admin", tags=["Tournament Admin"])


@router.get("/details", response_model=MatchAdminDetailRead)
async def get_tournament_admin_details(
    tournament_id: UUID,
    _admin: User = Depends(require_admin),
    session: AsyncSession = Depends(get_db_session),
):
    service = TournamentAdminService(session)
    return await service.get_tournament_details(tournament_id)


@router.post("/players/{user_id}/result", response_model=PlayerActionRead)
async def declare_player_result(
    tournament_id: UUID,
    user_id: UUID,
    payload: DeclareResultRequest,
    _admin: User = Depends(require_admin),
    session: AsyncSession = Depends(get_db_session),
):
    service = TournamentAdminService(session)
    return await service.declare_result(
        tournament_id,
        user_id,
        kills=payload.kills,
        is_winner=payload.is_winner,
        rank=payload.rank,
    )


@router.post("/publish-result", response_model=TournamentResultRead)
async def publish_tournament_result(
    tournament_id: UUID,
    admin: User = Depends(require_admin),
    session: AsyncSession = Depends(get_db_session),
):
    """
    One-click bridge from this page's already-declared winners
    (kills/is_winner/rank on each player) straight through the formal
    submit -> verify -> approve pipeline, so the public result page /
    Export JPG (which reads an APPROVED TournamentResult, not the
    player rows this admin page edits) has something to show.
    """
    service = TournamentAdminService(session)
    return await service.publish_result(tournament_id, current_user=admin)


@router.post("/players/{user_id}/pay", response_model=PlayerActionRead)
async def pay_tournament_winner(
    tournament_id: UUID,
    user_id: UUID,
    payload: PayWinnerRequest,
    admin: User = Depends(require_admin),
    session: AsyncSession = Depends(get_db_session),
):
    service = TournamentAdminService(session)
    return await service.pay_winner(
        tournament_id,
        user_id,
        amount=payload.amount,
        note=payload.note,
        current_user=admin,
    )