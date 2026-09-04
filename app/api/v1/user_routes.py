"""
User profile API routes.
"""
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.cache import cache_delete, cache_get, cache_set
from app.core.exceptions import NotFoundException
from app.database.session import get_db_session
from app.dependencies.auth import get_current_active_verified_user, get_current_user
from app.models.user import User
from app.schemas.leaderboard import MyTournamentStatsRead
from app.schemas.user import UserProfileUpdate, UserRead
from app.services.leaderboard_service import LeaderboardService
from app.services.participant_service import ParticipantService
from app.services.user_service import UserService

router = APIRouter(prefix="/users", tags=["Users"])

# NOTE: get_current_user (the auth dependency) still hits the DB on every
# request to load + validate the token's user -- that's unavoidable here,
# it's what actually authenticates the request. What we cache below is the
# *serialized profile payload* this endpoint returns, so a client that
# polls GET /me repeatedly (common right after login / on app resume)
# doesn't force the extra profile serialization/relationship access each
# time. Profile fields rarely change, so cache for an hour;
# update_my_profile invalidates immediately regardless of TTL.
_PROFILE_CACHE_TTL = 3600


def _profile_cache_key(user_id) -> str:
    return f"user:profile:{user_id}"


@router.get("/me", response_model=UserRead)
async def get_my_profile(current_user: User = Depends(get_current_user)):
    cache_key = _profile_cache_key(current_user.id)
    cached = await cache_get(cache_key)
    if cached is not None:
        return UserRead.model_validate(cached)

    result = UserRead.model_validate(current_user)
    await cache_set(cache_key, result.model_dump(mode="json"), ttl=_PROFILE_CACHE_TTL)
    return result


@router.get("/me/stats", response_model=MyTournamentStatsRead)
async def get_my_tournament_stats(
    current_user: User = Depends(get_current_active_verified_user),
    session: AsyncSession = Depends(get_db_session),
):
    """Profile-screen "Tournaments Joined / Won / Total Winnings / Win
    Rate" summary.

    `won` / `total_winnings` / `win_rate` come from PlayerStatistics
    (LeaderboardService), which both the admin distribute-prizes flow
    AND the custom 1v1 pay_winner flow keep up to date -- unlike
    /prize-payouts/me, which only the admin flow ever populates, so it
    under-reports wins for anyone who has only played custom
    tournaments. `joined` still comes from the real registration count.
    """
    _, joined = await ParticipantService(session).registration_history(
        current_user,
        page=1,
        page_size=1,
        status=None,
        sort_by="created_at",
        sort_order="desc",
    )

    try:
        stats = await LeaderboardService(session).get_player_statistics(current_user.id)
        won = stats.tournaments_won
        total_winnings = stats.prize_money_earned
        # Tournament win rate (won/played), not PlayerStatistics.win_rate
        # which is the per-match rate -- matches the old Flutter-side
        # (won/joined)*100 calculation the profile card expects.
        win_rate = (
            round((stats.tournaments_won / stats.tournaments_played) * 100, 2)
            if stats.tournaments_played
            else None
        )
    except NotFoundException:
        won = 0
        total_winnings = 0
        win_rate = None

    return MyTournamentStatsRead(
        joined=joined,
        won=won,
        total_winnings=total_winnings,
        win_rate=win_rate,
    )


@router.patch("/me", response_model=UserRead)
async def update_my_profile(
    payload: UserProfileUpdate,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
):
    service = UserService(session)
    updated_user = await service.update_profile(current_user.id, payload)
    await cache_delete(_profile_cache_key(current_user.id))
    return UserRead.model_validate(updated_user)