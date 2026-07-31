"""
Live Match & Real-Time Tournament API routes — Phase 12.
"""
import math
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.session import get_db_session
from app.dependencies.auth import get_current_active_verified_user
from app.models.live_match import LiveMatchEventType
from app.models.user import User
from app.schemas.live_match import (
    LiveLeaderboardRead,
    LiveMatchEventRead,
    LiveMatchRead,
    LiveMatchScoreRead,
    LiveMatchStatsRead,
    LiveMatchStatusRead,
    LiveTournamentProgressRead,
    LiveTournamentStateRead,
    LogEventRequest,
    PaginatedLiveMatchEvents,
    PaginatedLiveMatches,
    PlayerScoreUpdate,
    RoundTimerUpdate,
    TeamScoreUpdate,
)
from app.services.idempotency_service import IdempotencyService
from app.services.live_match_service import LiveMatchService, LiveTournamentService

router = APIRouter(tags=["Live Match & Real-Time Tournament"])


def _status_read(live) -> LiveMatchStatusRead:
    elapsed = LiveMatchService._elapsed_seconds(live)
    data = LiveMatchStatusRead.model_validate(live)
    data.elapsed_seconds = elapsed
    data.is_live = live.status.value == "live"
    return data


async def _with_idempotency(
    session: AsyncSession,
    idempotency_key: Optional[str],
    *,
    scope: str,
    user_id: UUID,
    payload: dict,
    action,
    status_code: int = 200,
):
    if not idempotency_key:
        result = await action()
        return result

    idempotency_service = IdempotencyService(session)
    async with idempotency_service.begin(
        scope=scope, key=idempotency_key, user_id=user_id, payload=payload
    ) as guard:
        if guard.replayed:
            return JSONResponse(status_code=guard.response_status_code, content=guard.response_body)
        result = await action()
        body = result.model_dump(mode="json") if hasattr(result, "model_dump") else result
        await guard.complete(status_code=status_code, body=body)
        return result


# ----------------------------------------------------------------------
# Lifecycle
# ----------------------------------------------------------------------
@router.post("/matches/{match_id}/live/start", response_model=LiveMatchRead)
async def start_live_match(
    match_id: UUID,
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
    current_user: User = Depends(get_current_active_verified_user),
    session: AsyncSession = Depends(get_db_session),
):
    service = LiveMatchService(session)

    async def _do():
        live = await service.start_match(match_id, current_user)
        return LiveMatchRead.model_validate(live)

    result = await _with_idempotency(
        session,
        idempotency_key,
        scope="live_match.start",
        user_id=current_user.id,
        payload={"match_id": str(match_id)},
        action=_do,
    )
    return result


@router.post("/matches/{match_id}/live/pause", response_model=LiveMatchRead)
async def pause_live_match(
    match_id: UUID,
    current_user: User = Depends(get_current_active_verified_user),
    session: AsyncSession = Depends(get_db_session),
):
    service = LiveMatchService(session)
    live = await service.pause_match(match_id, current_user)
    return LiveMatchRead.model_validate(live)


@router.post("/matches/{match_id}/live/resume", response_model=LiveMatchRead)
async def resume_live_match(
    match_id: UUID,
    current_user: User = Depends(get_current_active_verified_user),
    session: AsyncSession = Depends(get_db_session),
):
    service = LiveMatchService(session)
    live = await service.resume_match(match_id, current_user)
    return LiveMatchRead.model_validate(live)


@router.post("/matches/{match_id}/live/end", response_model=LiveMatchRead)
async def end_live_match(
    match_id: UUID,
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
    current_user: User = Depends(get_current_active_verified_user),
    session: AsyncSession = Depends(get_db_session),
):
    service = LiveMatchService(session)

    async def _do():
        live = await service.end_match(match_id, current_user)
        return LiveMatchRead.model_validate(live)

    result = await _with_idempotency(
        session,
        idempotency_key,
        scope="live_match.end",
        user_id=current_user.id,
        payload={"match_id": str(match_id)},
        action=_do,
    )
    return result


@router.post("/matches/{match_id}/live/cancel", response_model=LiveMatchRead)
async def cancel_live_match(
    match_id: UUID,
    reason: Optional[str] = Query(None, max_length=500),
    current_user: User = Depends(get_current_active_verified_user),
    session: AsyncSession = Depends(get_db_session),
):
    service = LiveMatchService(session)
    live = await service.cancel_match(match_id, current_user, reason=reason)
    return LiveMatchRead.model_validate(live)


@router.get("/matches/{match_id}/live/status", response_model=LiveMatchStatusRead)
async def get_live_match_status(
    match_id: UUID,
    session: AsyncSession = Depends(get_db_session),
):
    service = LiveMatchService(session)
    live = await service.get_status(match_id)
    return _status_read(live)


@router.patch("/matches/{match_id}/live/round-timer", response_model=LiveMatchRead)
async def update_round_timer(
    match_id: UUID,
    payload: RoundTimerUpdate,
    current_user: User = Depends(get_current_active_verified_user),
    session: AsyncSession = Depends(get_db_session),
):
    service = LiveMatchService(session)
    live = await service.update_round_timer(
        match_id, current_user, payload.round_number, payload.round_timer_seconds
    )
    return LiveMatchRead.model_validate(live)


# ----------------------------------------------------------------------
# Score updates
# ----------------------------------------------------------------------
@router.post("/matches/{match_id}/live/score/team", response_model=LiveMatchScoreRead)
async def update_team_score(
    match_id: UUID,
    payload: TeamScoreUpdate,
    current_user: User = Depends(get_current_active_verified_user),
    session: AsyncSession = Depends(get_db_session),
):
    service = LiveMatchService(session)
    row = await service.update_team_score(match_id, current_user, payload)
    return LiveMatchScoreRead.model_validate(row)


@router.post("/matches/{match_id}/live/score/player", response_model=LiveMatchScoreRead)
async def update_player_score(
    match_id: UUID,
    payload: PlayerScoreUpdate,
    current_user: User = Depends(get_current_active_verified_user),
    session: AsyncSession = Depends(get_db_session),
):
    service = LiveMatchService(session)
    row = await service.update_player_score(match_id, current_user, payload)
    return LiveMatchScoreRead.model_validate(row)


@router.get("/matches/{match_id}/live/leaderboard", response_model=LiveLeaderboardRead)
async def get_live_leaderboard(
    match_id: UUID,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    session: AsyncSession = Depends(get_db_session),
):
    service = LiveMatchService(session)
    items, _ = await service.get_leaderboard(match_id, page=page, page_size=page_size)
    return LiveLeaderboardRead(
        match_id=match_id, entries=[LiveMatchScoreRead.model_validate(i) for i in items]
    )


@router.get("/matches/{match_id}/live/stats", response_model=LiveMatchStatsRead)
async def get_live_match_stats(
    match_id: UUID,
    session: AsyncSession = Depends(get_db_session),
):
    service = LiveMatchService(session)
    stats = await service.get_stats(match_id)
    return LiveMatchStatsRead.model_validate(stats)


# ----------------------------------------------------------------------
# Events / timeline / activity feed
# ----------------------------------------------------------------------
@router.post("/matches/{match_id}/live/events", response_model=LiveMatchEventRead, status_code=201)
async def log_live_match_event(
    match_id: UUID,
    payload: LogEventRequest,
    current_user: User = Depends(get_current_active_verified_user),
    session: AsyncSession = Depends(get_db_session),
):
    service = LiveMatchService(session)
    event = await service.log_event(match_id, current_user, payload)
    return LiveMatchEventRead.model_validate(event)


@router.get("/matches/{match_id}/live/events", response_model=PaginatedLiveMatchEvents)
async def list_live_match_events(
    match_id: UUID,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    event_type: Optional[LiveMatchEventType] = Query(None),
    round_number: Optional[int] = Query(None, gt=0),
    sort_by: str = Query("sequence"),
    sort_order: str = Query("desc", pattern="^(?i)(asc|desc)$"),
    session: AsyncSession = Depends(get_db_session),
):
    service = LiveMatchService(session)
    items, total = await service.get_timeline(
        match_id,
        page=page,
        page_size=page_size,
        event_type=event_type,
        round_number=round_number,
        sort_by=sort_by,
        sort_order=sort_order,
    )
    total_pages = math.ceil(total / page_size) if total else 0
    return PaginatedLiveMatchEvents(
        items=[LiveMatchEventRead.model_validate(i) for i in items],
        total=total,
        page=page,
        page_size=page_size,
        total_pages=total_pages,
    )


@router.get("/matches/{match_id}/live/activity", response_model=PaginatedLiveMatchEvents)
async def get_live_match_activity_feed(
    match_id: UUID,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    session: AsyncSession = Depends(get_db_session),
):
    """Human-facing activity feed — same data as the timeline, newest first."""
    service = LiveMatchService(session)
    items, total = await service.get_timeline(
        match_id, page=page, page_size=page_size, sort_by="sequence", sort_order="desc"
    )
    total_pages = math.ceil(total / page_size) if total else 0
    return PaginatedLiveMatchEvents(
        items=[LiveMatchEventRead.model_validate(i) for i in items],
        total=total,
        page=page,
        page_size=page_size,
        total_pages=total_pages,
    )


# ----------------------------------------------------------------------
# Spectator / Active matches
# ----------------------------------------------------------------------
@router.get("/live/matches/active", response_model=PaginatedLiveMatches)
async def list_active_matches(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    tournament_id: Optional[UUID] = Query(None),
    session: AsyncSession = Depends(get_db_session),
):
    service = LiveMatchService(session)
    items, total = await service.list_active_matches(
        tournament_id=tournament_id, page=page, page_size=page_size
    )
    total_pages = math.ceil(total / page_size) if total else 0
    return PaginatedLiveMatches(
        items=[_status_read(i) for i in items],
        total=total,
        page=page,
        page_size=page_size,
        total_pages=total_pages,
    )


# ----------------------------------------------------------------------
# Live Tournament
# ----------------------------------------------------------------------
@router.get("/tournaments/{tournament_id}/live", response_model=LiveTournamentStateRead)
async def get_live_tournament_state(
    tournament_id: UUID,
    session: AsyncSession = Depends(get_db_session),
):
    service = LiveTournamentService(session)
    state = await service.get_state(tournament_id)
    return LiveTournamentStateRead.model_validate(state)


@router.get("/tournaments/{tournament_id}/live/progress", response_model=LiveTournamentProgressRead)
async def get_live_tournament_progress(
    tournament_id: UUID,
    session: AsyncSession = Depends(get_db_session),
):
    service = LiveTournamentService(session)
    progress = await service.get_progress(tournament_id)
    return LiveTournamentProgressRead.model_validate(progress)
