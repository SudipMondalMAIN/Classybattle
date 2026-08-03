"""
Team System & Invite Management API routes (Phase 6).
"""
import math
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.session import get_db_session
from app.dependencies.auth import get_current_active_verified_user, require_admin
from app.models.team import TeamStatus
from app.models.user import User
from app.schemas.team import (
    AutoAssignRequest,
    AutoAssignResult,
    PaginatedTeams,
    RemoveMember,
    TeamCreate,
    TeamJoin,
    TeamListItem,
    TeamLockUpdate,
    TeamMemberRead,
    TeamRead,
    TeamReadWithMembers,
    TeamUpdate,
    TransferCaptain,
)
from app.services.auto_team_assignment_service import AutoTeamAssignmentService
from app.services.team_service import TeamService

router = APIRouter(tags=["Team System"])


# ----------------------------------------------------------------------
# Team creation & invite-code joining (scoped to a tournament)
# ----------------------------------------------------------------------
@router.post(
    "/tournaments/{tournament_id}/teams",
    response_model=TeamRead,
    status_code=201,
)
async def create_team(
    tournament_id: UUID,
    payload: TeamCreate,
    current_user: User = Depends(get_current_active_verified_user),
    session: AsyncSession = Depends(get_db_session),
):
    service = TeamService(session)
    team = await service.create_team(tournament_id, payload, current_user)
    return TeamRead.model_validate(team)


@router.post(
    "/tournaments/{tournament_id}/teams/join",
    response_model=TeamRead,
)
async def join_team(
    tournament_id: UUID,
    payload: TeamJoin,
    current_user: User = Depends(get_current_active_verified_user),
    session: AsyncSession = Depends(get_db_session),
):
    service = TeamService(session)
    team = await service.join_team(tournament_id, payload.invite_code, current_user)
    return TeamRead.model_validate(team)


@router.get(
    "/tournaments/{tournament_id}/teams",
    response_model=PaginatedTeams,
)
async def list_tournament_teams(
    tournament_id: UUID,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    status: Optional[TeamStatus] = Query(None),
    search: Optional[str] = Query(None, max_length=200),
    sort_by: str = Query("created_at"),
    sort_order: str = Query("desc", pattern="^(?i)(asc|desc)$"),
    session: AsyncSession = Depends(get_db_session),
):
    service = TeamService(session)
    items, total = await service.list_teams_public(
        tournament_id,
        page=page,
        page_size=page_size,
        status=status,
        search=search,
        sort_by=sort_by,
        sort_order=sort_order,
    )
    total_pages = math.ceil(total / page_size) if total else 0
    return PaginatedTeams(
        items=[TeamListItem.model_validate(t) for t in items],
        total=total,
        page=page,
        page_size=page_size,
        total_pages=total_pages,
    )


@router.get(
    "/tournaments/{tournament_id}/teams/manage",
    response_model=PaginatedTeams,
)
async def list_tournament_teams_organizer(
    tournament_id: UUID,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    status: Optional[TeamStatus] = Query(None),
    search: Optional[str] = Query(None, max_length=200),
    sort_by: str = Query("created_at"),
    sort_order: str = Query("desc", pattern="^(?i)(asc|desc)$"),
    current_user: User = Depends(get_current_active_verified_user),
    session: AsyncSession = Depends(get_db_session),
):
    service = TeamService(session)
    items, total = await service.list_teams_organizer(
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
    return PaginatedTeams(
        items=[TeamListItem.model_validate(t) for t in items],
        total=total,
        page=page,
        page_size=page_size,
        total_pages=total_pages,
    )


# ----------------------------------------------------------------------
# Individual team management
# ----------------------------------------------------------------------
@router.get("/teams/short/{short_id}", response_model=TeamReadWithMembers)
async def get_team_by_short_id(
    short_id: int,
    current_user: User = Depends(require_admin),
    session: AsyncSession = Depends(get_db_session),
):
    """Admin lookup by the human-friendly 8-digit short_id."""
    service = TeamService(session)
    team = await service.get_team_by_short_id(short_id)
    return TeamReadWithMembers.model_validate(team)


@router.get("/teams/{team_id}", response_model=TeamReadWithMembers)
async def get_team_details(
    team_id: UUID,
    session: AsyncSession = Depends(get_db_session),
):
    service = TeamService(session)
    team = await service.get_team_details(team_id)
    return TeamReadWithMembers.model_validate(team)


@router.patch("/teams/{team_id}", response_model=TeamRead)
async def update_team(
    team_id: UUID,
    payload: TeamUpdate,
    current_user: User = Depends(get_current_active_verified_user),
    session: AsyncSession = Depends(get_db_session),
):
    service = TeamService(session)
    team = await service.update_team(team_id, payload, current_user)
    return TeamRead.model_validate(team)


@router.delete("/teams/{team_id}", status_code=204)
async def delete_team(
    team_id: UUID,
    current_user: User = Depends(get_current_active_verified_user),
    session: AsyncSession = Depends(get_db_session),
):
    service = TeamService(session)
    await service.delete_team(team_id, current_user)


@router.get("/teams/{team_id}/members", response_model=list[TeamMemberRead])
async def get_team_members(
    team_id: UUID,
    session: AsyncSession = Depends(get_db_session),
):
    service = TeamService(session)
    members = await service.get_team_members(team_id)
    return [TeamMemberRead.model_validate(m) for m in members]


@router.post("/teams/{team_id}/leave", response_model=TeamRead)
async def leave_team(
    team_id: UUID,
    current_user: User = Depends(get_current_active_verified_user),
    session: AsyncSession = Depends(get_db_session),
):
    service = TeamService(session)
    team = await service.leave_team(team_id, current_user)
    return TeamRead.model_validate(team)


@router.post("/teams/{team_id}/members/remove", response_model=TeamRead)
async def remove_member(
    team_id: UUID,
    payload: RemoveMember,
    current_user: User = Depends(get_current_active_verified_user),
    session: AsyncSession = Depends(get_db_session),
):
    service = TeamService(session)
    team = await service.remove_member(team_id, payload.user_id, current_user)
    return TeamRead.model_validate(team)


@router.post("/teams/{team_id}/transfer-captain", response_model=TeamRead)
async def transfer_captain(
    team_id: UUID,
    payload: TransferCaptain,
    current_user: User = Depends(get_current_active_verified_user),
    session: AsyncSession = Depends(get_db_session),
):
    service = TeamService(session)
    team = await service.transfer_captain(team_id, payload.new_captain_user_id, current_user)
    return TeamRead.model_validate(team)


@router.patch("/teams/{team_id}/lock", response_model=TeamRead)
async def set_team_lock(
    team_id: UUID,
    payload: TeamLockUpdate,
    current_user: User = Depends(get_current_active_verified_user),
    session: AsyncSession = Depends(get_db_session),
):
    service = TeamService(session)
    team = await service.set_lock(team_id, payload.is_locked, current_user)
    return TeamRead.model_validate(team)


# ----------------------------------------------------------------------
# Organizer / Admin moderation
# ----------------------------------------------------------------------
@router.delete("/teams/{team_id}/organizer", status_code=204)
async def organizer_remove_team(
    team_id: UUID,
    current_user: User = Depends(get_current_active_verified_user),
    session: AsyncSession = Depends(get_db_session),
):
    service = TeamService(session)
    await service.organizer_remove_team(team_id, current_user)


@router.post(
    "/tournaments/{tournament_id}/teams/organizer/remove-player",
    status_code=204,
)
async def organizer_remove_player(
    tournament_id: UUID,
    payload: RemoveMember,
    current_user: User = Depends(get_current_active_verified_user),
    session: AsyncSession = Depends(get_db_session),
):
    service = TeamService(session)
    await service.organizer_remove_player(tournament_id, payload.user_id, current_user)


# ----------------------------------------------------------------------
# Automatic Random Team Assignment (AUTO_RANDOM tournaments)
# ----------------------------------------------------------------------
@router.post(
    "/tournaments/{tournament_id}/teams/auto-assign",
    response_model=AutoAssignResult,
)
async def auto_assign_teams(
    tournament_id: UUID,
    payload: AutoAssignRequest,
    current_user: User = Depends(get_current_active_verified_user),
    session: AsyncSession = Depends(get_db_session),
):
    service = AutoTeamAssignmentService(session)
    result = await service.assign_teams(
        tournament_id,
        current_user,
        team_size=payload.team_size,
        seed=payload.seed,
    )
    return AutoAssignResult(
        teams_created=result["teams_created"],
        players_assigned=result["players_assigned"],
        unassigned_players=result["unassigned_players"],
        teams=[TeamReadWithMembers.model_validate(t) for t in result["teams"]],
    )
