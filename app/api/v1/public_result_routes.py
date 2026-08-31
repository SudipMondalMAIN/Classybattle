"""
Public Tournament Result routes — for result.classybattle.online.

Patch notes:
- New file: app/api/v1/public_result_routes.py (register in app/api/v1/router.py)
- No authentication required — these are read-only, public-safe endpoints.
- Only ever exposes tournaments whose TournamentResult.status == APPROVED.
  A submitted/verified-but-not-yet-approved result is never shown here —
  admin approval is the public-visibility gate, so a wrong/disputed result
  never reaches the public site.
- Never exposes: user email, phone number, wallet balance, payment details,
  or anything beyond name + per-game UID + placement + prize amount.
- The JPG endpoint generates the image on-the-fly (Pillow) — the bytes are
  cached (see below) but never written to disk/DB/object storage.

Caching
-------
An APPROVED result is effectively immutable — once published it isn't
expected to change — so repeated requests for the same (usually old)
tournament would otherwise re-hit Postgres (and re-run Pillow rendering
for the image) every single time, forever. That's wasted DB load for
data that never changes.

Reuses the repo's existing Redis cache layer (app/core/cache.py) — same
fail-open behavior: if REDIS_URL isn't configured or Redis is briefly
down, every call just falls through to the DB/Pillow as before. Nothing
breaks, it simply stops being fast.

- Detail (`GET /{id}`) — cached CACHE_TTL_RESULT (7 days).
- Image (`GET /{id}/image`) — the rendered JPEG bytes are cached
  CACHE_TTL_RESULT too, so a hit skips both the DB query AND the Pillow
  render.
- List (`GET ""`) — cached CACHE_TTL_LIST (60s) only, keyed by the exact
  filter params, since new results are approved over time and the list
  should reflect that quickly.

If a result is ever corrected/re-approved after admin edits, invalidate
manually with `cache_delete_prefix(f"public_result:{tournament_id}")`
from wherever that re-approval happens — not wired up here since this
repo's current TournamentResult flow has no "edit after approve" path.
"""
import base64
from datetime import date, datetime
from io import BytesIO
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response, StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.cache import cache_get, cache_set
from app.core.exceptions import NotFoundException
from app.database.session import get_db_session
from app.models.tournament import Tournament
from app.models.tournament_participant import TournamentParticipant
from app.models.tournament_result import TournamentResult, TournamentResultStatus
from app.models.tournament_winner import TournamentWinner
from app.schemas.public_result import PublicResultDetail, PublicResultSummary
from app.services.result_image_service import ResultImageService

router = APIRouter(prefix="/public/results", tags=["Public Results"])

CACHE_TTL_RESULT = 7 * 24 * 3600  # approved results are effectively immutable
CACHE_TTL_LIST = 60  # list keeps moving as new results get approved


async def _get_approved_result(session: AsyncSession, tournament_id: UUID) -> TournamentResult:
    stmt = (
        select(TournamentResult)
        .where(
            TournamentResult.tournament_id == tournament_id,
            TournamentResult.status == TournamentResultStatus.APPROVED,
        )
        .options(
            selectinload(TournamentResult.tournament),
            selectinload(TournamentResult.winners)
            .selectinload(TournamentWinner.participant),
            selectinload(TournamentResult.winners).selectinload(TournamentWinner.team),
        )
    )
    result = (await session.execute(stmt)).scalar_one_or_none()
    if result is None:
        raise NotFoundException("No published result for this tournament")
    return result


async def _build_detail(session: AsyncSession, tournament_id: UUID) -> PublicResultDetail:
    """Shared by the detail and image endpoints so both benefit from the
    same cache entry instead of maintaining two separate caches."""
    cache_key = f"public_result:detail:{tournament_id}"
    cached = await cache_get(cache_key)
    if cached is not None:
        return PublicResultDetail.model_validate(cached)

    result = await _get_approved_result(session, tournament_id)
    participants_stmt = (
        select(TournamentParticipant)
        .where(TournamentParticipant.tournament_id == tournament_id)
        .options(
            selectinload(TournamentParticipant.participant),
            selectinload(TournamentParticipant.team),
        )
    )
    participants = (await session.execute(participants_stmt)).scalars().all()
    detail = PublicResultDetail.build(tournament=result.tournament, winners=result.winners, participants=participants)

    await cache_set(cache_key, detail.model_dump(mode="json"), ttl=CACHE_TTL_RESULT)
    return detail


@router.get("", response_model=list[PublicResultSummary])
async def list_public_results(
    date_from: Optional[date] = Query(None, description="Filter: tournaments starting on/after this date"),
    date_to: Optional[date] = Query(None, description="Filter: tournaments starting on/before this date"),
    game_id: Optional[UUID] = Query(None),
    limit: int = Query(30, le=100),
    offset: int = Query(0, ge=0),
    session: AsyncSession = Depends(get_db_session),
):
    """
    Browse published results — the listing that powers result.classybattle.online's
    home page and date filter. Only APPROVED results are returned.
    """
    cache_key = f"public_result:list:{date_from}:{date_to}:{game_id}:{limit}:{offset}"
    cached = await cache_get(cache_key)
    if cached is not None:
        return [PublicResultSummary.model_validate(row) for row in cached]

    stmt = (
        select(TournamentResult)
        .join(Tournament, TournamentResult.tournament_id == Tournament.id)
        .where(TournamentResult.status == TournamentResultStatus.APPROVED)
        .options(selectinload(TournamentResult.tournament))
        .order_by(Tournament.starts_at.desc())
        .limit(limit)
        .offset(offset)
    )
    if date_from:
        stmt = stmt.where(Tournament.starts_at >= datetime.combine(date_from, datetime.min.time()))
    if date_to:
        stmt = stmt.where(Tournament.starts_at <= datetime.combine(date_to, datetime.max.time()))
    if game_id:
        stmt = stmt.where(Tournament.game_id == game_id)

    rows = (await session.execute(stmt)).scalars().all()
    summaries = [
        PublicResultSummary(
            tournament_id=r.tournament.id,
            tournament_uid=r.tournament.tournament_uid,
            title=r.tournament.title,
            starts_at=r.tournament.starts_at,
            prize_pool=r.tournament.prize_pool,
            participant_count=r.tournament.current_players,
            approved_at=r.approved_at,
        )
        for r in rows
    ]
    await cache_set(cache_key, [s.model_dump(mode="json") for s in summaries], ttl=CACHE_TTL_LIST)
    return summaries


@router.get("/{tournament_id}", response_model=PublicResultDetail)
async def get_public_result(tournament_id: UUID, session: AsyncSession = Depends(get_db_session)):
    """Full public result — tournament info, winners, and participant list, each with game UID."""
    return await _build_detail(session, tournament_id)


@router.get("/{tournament_id}/image")
async def get_public_result_image(tournament_id: UUID, session: AsyncSession = Depends(get_db_session)):
    """
    Shareable JPG for this result. The rendered bytes are cached alongside
    the detail data (see module docstring) — a cache hit skips the DB
    query AND the Pillow render entirely.
    """
    image_cache_key = f"public_result:image:{tournament_id}"
    cached_b64 = await cache_get(image_cache_key)
    if cached_b64 is not None:
        # Cache hit: reuse the already-cached detail for the filename too,
        # so a hit never touches the DB at all.
        detail = await _build_detail(session, tournament_id)
        image_bytes = base64.b64decode(cached_b64)
    else:
        detail = await _build_detail(session, tournament_id)
        buffer: BytesIO = ResultImageService.render(detail)
        image_bytes = buffer.read()
        await cache_set(image_cache_key, base64.b64encode(image_bytes).decode("ascii"), ttl=CACHE_TTL_RESULT)

    return Response(
        content=image_bytes,
        media_type="image/jpeg",
        headers={
            "Content-Disposition": f'inline; filename="{detail.tournament_uid}-result.jpg"',
            # Public + long-lived: browsers/CDNs may cache too, since an
            # approved result's image never changes.
            "Cache-Control": "public, max-age=86400",
        },
    )
