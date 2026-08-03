"""
Admin match-details routes (Raj's flow): one page per match showing
everyone who joined (with their in-game nickname + UID), where Admin
enters kills, declares the winner(s), and pays out the winning amount
directly to the player's wallet.
"""
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.session import get_db_session
from app.dependencies.auth import require_admin
from app.models.user import User
from app.schemas.match_admin import (
    DeclareResultRequest,
    MatchAdminDetailRead,
    MatchAdminPlayerRead,
    PayWinnerRequest,
)
from app.services.match_admin_service import MatchAdminService

router = APIRouter(prefix="/admin/matches", tags=["Admin — Match Details"])


@router.get("/{match_id}/details", response_model=MatchAdminDetailRead)
async def get_match_admin_details(
    match_id: UUID,
    current_user: User = Depends(require_admin),
    session: AsyncSession = Depends(get_db_session),
):
    """Everything Admin needs on one screen: room info, entry fee/prize
    pool, and every joined player with their game nickname + UID, kills,
    and winner/payout status."""
    service = MatchAdminService(session)
    return await service.get_match_details(match_id)


@router.patch("/{match_id}/players/{user_id}/result", response_model=MatchAdminPlayerRead)
async def declare_player_result(
    match_id: UUID,
    user_id: UUID,
    payload: DeclareResultRequest,
    current_user: User = Depends(require_admin),
    session: AsyncSession = Depends(get_db_session),
):
    """Admin: set a player's kill count and/or declare them a winner."""
    service = MatchAdminService(session)
    row = await service.declare_result(
        match_id, user_id, kills=payload.kills, is_winner=payload.is_winner
    )
    details = await service.get_match_details(match_id)
    for p in details.players:
        if p.user_id == user_id:
            return p
    return row


@router.post("/{match_id}/players/{user_id}/pay", response_model=MatchAdminPlayerRead)
async def pay_match_winner(
    match_id: UUID,
    user_id: UUID,
    payload: PayWinnerRequest,
    current_user: User = Depends(require_admin),
    session: AsyncSession = Depends(get_db_session),
):
    """Admin: credit the winning amount straight to this player's wallet.
    Only works once the player has been declared a winner, and only
    once per match (can't double-pay by mistake)."""
    service = MatchAdminService(session)
    await service.pay_winner(
        match_id, user_id, amount=payload.amount, note=payload.note, current_user=current_user
    )
    details = await service.get_match_details(match_id)
    for p in details.players:
        if p.user_id == user_id:
            return p
    raise RuntimeError("unreachable")
