"""
Match Result & Winner Management API routes — Phase 11.
"""
import math
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.session import get_db_session
from app.dependencies.auth import get_current_active_verified_user, require_admin
from app.models.match_result import MatchResultStatus
from app.models.user import User
from app.schemas.match_result import (
    AuditHistoryEntry,
    DeclareWinnersRequest,
    MatchResultRead,
    MatchResultReject,
    MatchResultSubmit,
    MatchResultUpdateRequest,
    MatchWinnerRead,
    PaginatedMatchResults,
    PaginatedMatchWinners,
)
from app.services.idempotency_service import IdempotencyService
from app.services.match_result_service import MatchResultService

router = APIRouter(tags=["Match Results & Winners"])


def _paginate(total: int, page: int, page_size: int) -> int:
    return math.ceil(total / page_size) if total else 0


# ----------------------------------------------------------------------
# Submit / Update / Delete
# ----------------------------------------------------------------------
@router.post(
    "/matches/{match_id}/result",
    response_model=MatchResultRead,
    status_code=201,
)
async def submit_match_result(
    match_id: UUID,
    payload: MatchResultSubmit,
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
    current_user: User = Depends(get_current_active_verified_user),
    session: AsyncSession = Depends(get_db_session),
):
    service = MatchResultService(session)

    if not idempotency_key:
        result = await service.submit_result(match_id, payload, current_user)
        return MatchResultRead.model_validate(result)

    idempotency_service = IdempotencyService(session)
    async with idempotency_service.begin(
        scope="match.submit_result",
        key=idempotency_key,
        user_id=current_user.id,
        payload={"match_id": str(match_id), **payload.model_dump(mode="json")},
    ) as guard:
        if guard.replayed:
            return JSONResponse(status_code=guard.response_status_code, content=guard.response_body)

        result = await service.submit_result(match_id, payload, current_user)
        body = MatchResultRead.model_validate(result).model_dump(mode="json")
        await guard.complete(status_code=201, body=body)
        return body


@router.patch("/matches/{match_id}/result", response_model=MatchResultRead)
async def update_match_result(
    match_id: UUID,
    payload: MatchResultUpdateRequest,
    current_user: User = Depends(get_current_active_verified_user),
    session: AsyncSession = Depends(get_db_session),
):
    service = MatchResultService(session)
    result = await service.update_result(match_id, payload, current_user)
    return MatchResultRead.model_validate(result)


@router.delete("/admin/matches/{match_id}/result", status_code=204)
async def delete_match_result(
    match_id: UUID,
    admin: User = Depends(require_admin),
    session: AsyncSession = Depends(get_db_session),
):
    service = MatchResultService(session)
    await service.delete_result(match_id, admin)
    return None


@router.get("/matches/{match_id}/result", response_model=MatchResultRead)
async def get_match_result(
    match_id: UUID,
    session: AsyncSession = Depends(get_db_session),
):
    service = MatchResultService(session)
    result = await service.get_result(match_id)
    return MatchResultRead.model_validate(result)


# ----------------------------------------------------------------------
# Verify / Approve / Reject
# ----------------------------------------------------------------------
@router.post("/admin/matches/{match_id}/result/verify", response_model=MatchResultRead)
async def verify_match_result(
    match_id: UUID,
    admin: User = Depends(require_admin),
    session: AsyncSession = Depends(get_db_session),
):
    service = MatchResultService(session)
    result = await service.verify_result(match_id, admin)
    return MatchResultRead.model_validate(result)


@router.post("/admin/matches/{match_id}/result/approve", response_model=MatchResultRead)
async def approve_match_result(
    match_id: UUID,
    admin: User = Depends(require_admin),
    session: AsyncSession = Depends(get_db_session),
):
    service = MatchResultService(session)
    result = await service.approve_result(match_id, admin)
    return MatchResultRead.model_validate(result)


@router.post("/admin/matches/{match_id}/result/reject", response_model=MatchResultRead)
async def reject_match_result(
    match_id: UUID,
    payload: MatchResultReject,
    admin: User = Depends(require_admin),
    session: AsyncSession = Depends(get_db_session),
):
    service = MatchResultService(session)
    result = await service.reject_result(match_id, payload.reason, admin)
    return MatchResultRead.model_validate(result)


# ----------------------------------------------------------------------
# Winner declaration
# ----------------------------------------------------------------------
@router.post(
    "/admin/matches/{match_id}/winners/auto-select",
    response_model=list[MatchWinnerRead],
    status_code=201,
)
async def auto_select_match_winners(
    match_id: UUID,
    admin: User = Depends(require_admin),
    session: AsyncSession = Depends(get_db_session),
):
    service = MatchResultService(session)
    winners = await service.auto_select_winners(match_id, admin)
    return [MatchWinnerRead.model_validate(w) for w in winners]


@router.post(
    "/admin/matches/{match_id}/winners",
    response_model=list[MatchWinnerRead],
    status_code=201,
)
async def declare_match_winners(
    match_id: UUID,
    payload: DeclareWinnersRequest,
    admin: User = Depends(require_admin),
    session: AsyncSession = Depends(get_db_session),
):
    service = MatchResultService(session)
    winners = await service.declare_winners(match_id, payload, admin)
    return [MatchWinnerRead.model_validate(w) for w in winners]


@router.get("/matches/{match_id}/winners", response_model=list[MatchWinnerRead])
async def list_match_winners(
    match_id: UUID,
    session: AsyncSession = Depends(get_db_session),
):
    service = MatchResultService(session)
    winners = await service.list_match_winners(match_id)
    return [MatchWinnerRead.model_validate(w) for w in winners]


# ----------------------------------------------------------------------
# Admin listing (pagination / filtering / sorting)
# ----------------------------------------------------------------------
@router.get("/admin/match-results", response_model=PaginatedMatchResults)
async def admin_list_match_results(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    tournament_id: Optional[UUID] = Query(None),
    match_id: Optional[UUID] = Query(None),
    status: Optional[MatchResultStatus] = Query(None),
    sort_by: str = Query("created_at"),
    sort_order: str = Query("desc", pattern="^(?i)(asc|desc)$"),
    _admin: User = Depends(require_admin),
    session: AsyncSession = Depends(get_db_session),
):
    service = MatchResultService(session)
    items, total = await service.list_results(
        page=page,
        page_size=page_size,
        tournament_id=tournament_id,
        match_id=match_id,
        status=status,
        sort_by=sort_by,
        sort_order=sort_order,
    )
    return PaginatedMatchResults(
        items=[MatchResultRead.model_validate(r) for r in items],
        total=total, page=page, page_size=page_size, total_pages=_paginate(total, page, page_size),
    )


# ----------------------------------------------------------------------
# History
# ----------------------------------------------------------------------
@router.get("/matches/{match_id}/result/history", response_model=list[AuditHistoryEntry])
async def get_match_result_history(
    match_id: UUID,
    session: AsyncSession = Depends(get_db_session),
):
    service = MatchResultService(session)
    history = await service.get_result_history(match_id)
    return [AuditHistoryEntry.model_validate(h) for h in history]


@router.get("/matches/{match_id}/winners/history", response_model=list[AuditHistoryEntry])
async def get_match_winner_history(
    match_id: UUID,
    session: AsyncSession = Depends(get_db_session),
):
    service = MatchResultService(session)
    history = await service.get_winner_history(match_id)
    return [AuditHistoryEntry.model_validate(h) for h in history]
