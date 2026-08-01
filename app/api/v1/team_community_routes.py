"""
Team Community System API routes — Phase 15B.

Covers Team Invitations, Team Join Requests, Team Announcements, and the
Team Activity Feed / Member History / Event History. Mounted alongside the
existing `/teams` routes from Phase 6 (team_routes.py) without touching
that module, preserving full backward compatibility.
"""
import math
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.session import get_db_session
from app.dependencies.auth import get_current_active_verified_user
from app.models.team_community import (
    TeamActivityType,
    TeamInvitationStatus,
    TeamJoinRequestStatus,
)
from app.models.user import User
from app.schemas.team_community import (
    PaginatedTeamActivityFeed,
    PaginatedTeamAnnouncements,
    PaginatedTeamInvitations,
    PaginatedTeamJoinRequests,
    TeamActivityFeedEntryRead,
    TeamAnnouncementCreate,
    TeamAnnouncementRead,
    TeamAnnouncementUpdate,
    TeamInvitationCreate,
    TeamInvitationRead,
    TeamJoinRequestCreate,
    TeamJoinRequestRead,
)
from app.services.idempotency_service import IdempotencyService
from app.services.team_community_service import (
    TeamActivityFeedService,
    TeamAnnouncementService,
    TeamInvitationService,
    TeamJoinRequestService,
)

router = APIRouter(tags=["Team Community"])


def _total_pages(total: int, page_size: int) -> int:
    return math.ceil(total / page_size) if total else 0


# ----------------------------------------------------------------------
# Team Invitations
# ----------------------------------------------------------------------
@router.post(
    "/teams/{team_id}/invitations",
    response_model=TeamInvitationRead,
    status_code=201,
)
async def create_team_invitation(
    team_id: UUID,
    payload: TeamInvitationCreate,
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
    current_user: User = Depends(get_current_active_verified_user),
    session: AsyncSession = Depends(get_db_session),
):
    service = TeamInvitationService(session)

    if not idempotency_key:
        invitation = await service.invite(team_id, current_user, payload.invitee_id, payload.message)
        return TeamInvitationRead.model_validate(invitation)

    idempotency_service = IdempotencyService(session)
    async with idempotency_service.begin(
        scope="team.invitation.create",
        key=idempotency_key,
        user_id=current_user.id,
        payload={"team_id": str(team_id), **payload.model_dump(mode="json")},
    ) as guard:
        if guard.replayed:
            return JSONResponse(status_code=guard.response_status_code, content=guard.response_body)

        invitation = await service.invite(team_id, current_user, payload.invitee_id, payload.message)
        result = TeamInvitationRead.model_validate(invitation)
        body = result.model_dump(mode="json")
        await guard.complete(status_code=201, body=body)
        await session.commit()
        return result


@router.get("/teams/{team_id}/invitations", response_model=PaginatedTeamInvitations)
async def list_team_invitations(
    team_id: UUID,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    status: Optional[TeamInvitationStatus] = Query(None),
    sort_by: str = Query("created_at"),
    sort_order: str = Query("desc", pattern="^(?i)(asc|desc)$"),
    current_user: User = Depends(get_current_active_verified_user),
    session: AsyncSession = Depends(get_db_session),
):
    service = TeamInvitationService(session)
    items, total = await service.list_for_team(
        team_id,
        current_user,
        page=page,
        page_size=page_size,
        status=status,
        sort_by=sort_by,
        sort_order=sort_order,
    )
    return PaginatedTeamInvitations(
        items=[TeamInvitationRead.model_validate(i) for i in items],
        total=total,
        page=page,
        page_size=page_size,
        total_pages=_total_pages(total, page_size),
    )


@router.get("/invitations/me", response_model=PaginatedTeamInvitations)
async def list_my_incoming_invitations(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    current_user: User = Depends(get_current_active_verified_user),
    session: AsyncSession = Depends(get_db_session),
):
    service = TeamInvitationService(session)
    items, total = await service.list_incoming(current_user, page=page, page_size=page_size)
    return PaginatedTeamInvitations(
        items=[TeamInvitationRead.model_validate(i) for i in items],
        total=total,
        page=page,
        page_size=page_size,
        total_pages=_total_pages(total, page_size),
    )


@router.post("/invitations/{invitation_id}/accept", response_model=TeamInvitationRead)
async def accept_team_invitation(
    invitation_id: UUID,
    current_user: User = Depends(get_current_active_verified_user),
    session: AsyncSession = Depends(get_db_session),
):
    service = TeamInvitationService(session)
    invitation = await service.accept(current_user, invitation_id)
    return TeamInvitationRead.model_validate(invitation)


@router.post("/invitations/{invitation_id}/reject", response_model=TeamInvitationRead)
async def reject_team_invitation(
    invitation_id: UUID,
    current_user: User = Depends(get_current_active_verified_user),
    session: AsyncSession = Depends(get_db_session),
):
    service = TeamInvitationService(session)
    invitation = await service.reject(current_user, invitation_id)
    return TeamInvitationRead.model_validate(invitation)


@router.post("/invitations/{invitation_id}/cancel", response_model=TeamInvitationRead)
async def cancel_team_invitation(
    invitation_id: UUID,
    current_user: User = Depends(get_current_active_verified_user),
    session: AsyncSession = Depends(get_db_session),
):
    service = TeamInvitationService(session)
    invitation = await service.cancel(current_user, invitation_id)
    return TeamInvitationRead.model_validate(invitation)


# ----------------------------------------------------------------------
# Team Join Requests
# ----------------------------------------------------------------------
@router.post(
    "/teams/{team_id}/join-requests",
    response_model=TeamJoinRequestRead,
    status_code=201,
)
async def create_team_join_request(
    team_id: UUID,
    payload: TeamJoinRequestCreate,
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
    current_user: User = Depends(get_current_active_verified_user),
    session: AsyncSession = Depends(get_db_session),
):
    service = TeamJoinRequestService(session)

    if not idempotency_key:
        join_request = await service.request_to_join(team_id, current_user, payload.message)
        return TeamJoinRequestRead.model_validate(join_request)

    idempotency_service = IdempotencyService(session)
    async with idempotency_service.begin(
        scope="team.join_request.create",
        key=idempotency_key,
        user_id=current_user.id,
        payload={"team_id": str(team_id), **payload.model_dump(mode="json")},
    ) as guard:
        if guard.replayed:
            return JSONResponse(status_code=guard.response_status_code, content=guard.response_body)

        join_request = await service.request_to_join(team_id, current_user, payload.message)
        result = TeamJoinRequestRead.model_validate(join_request)
        body = result.model_dump(mode="json")
        await guard.complete(status_code=201, body=body)
        await session.commit()
        return result


@router.get("/teams/{team_id}/join-requests", response_model=PaginatedTeamJoinRequests)
async def list_team_join_requests(
    team_id: UUID,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    status: Optional[TeamJoinRequestStatus] = Query(None),
    sort_by: str = Query("created_at"),
    sort_order: str = Query("desc", pattern="^(?i)(asc|desc)$"),
    current_user: User = Depends(get_current_active_verified_user),
    session: AsyncSession = Depends(get_db_session),
):
    service = TeamJoinRequestService(session)
    items, total = await service.list_for_team(
        team_id,
        current_user,
        page=page,
        page_size=page_size,
        status=status,
        sort_by=sort_by,
        sort_order=sort_order,
    )
    return PaginatedTeamJoinRequests(
        items=[TeamJoinRequestRead.model_validate(i) for i in items],
        total=total,
        page=page,
        page_size=page_size,
        total_pages=_total_pages(total, page_size),
    )


@router.get("/join-requests/me", response_model=PaginatedTeamJoinRequests)
async def list_my_outgoing_join_requests(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    current_user: User = Depends(get_current_active_verified_user),
    session: AsyncSession = Depends(get_db_session),
):
    service = TeamJoinRequestService(session)
    items, total = await service.list_outgoing(current_user, page=page, page_size=page_size)
    return PaginatedTeamJoinRequests(
        items=[TeamJoinRequestRead.model_validate(i) for i in items],
        total=total,
        page=page,
        page_size=page_size,
        total_pages=_total_pages(total, page_size),
    )


@router.post("/teams/{team_id}/join-requests/{request_id}/accept", response_model=TeamJoinRequestRead)
async def accept_team_join_request(
    team_id: UUID,
    request_id: UUID,
    current_user: User = Depends(get_current_active_verified_user),
    session: AsyncSession = Depends(get_db_session),
):
    service = TeamJoinRequestService(session)
    join_request = await service.accept(team_id, current_user, request_id)
    return TeamJoinRequestRead.model_validate(join_request)


@router.post("/teams/{team_id}/join-requests/{request_id}/reject", response_model=TeamJoinRequestRead)
async def reject_team_join_request(
    team_id: UUID,
    request_id: UUID,
    current_user: User = Depends(get_current_active_verified_user),
    session: AsyncSession = Depends(get_db_session),
):
    service = TeamJoinRequestService(session)
    join_request = await service.reject(team_id, current_user, request_id)
    return TeamJoinRequestRead.model_validate(join_request)


@router.post("/join-requests/{request_id}/cancel", response_model=TeamJoinRequestRead)
async def cancel_team_join_request(
    request_id: UUID,
    current_user: User = Depends(get_current_active_verified_user),
    session: AsyncSession = Depends(get_db_session),
):
    service = TeamJoinRequestService(session)
    join_request = await service.cancel(current_user, request_id)
    return TeamJoinRequestRead.model_validate(join_request)


# ----------------------------------------------------------------------
# Team Announcements
# ----------------------------------------------------------------------
@router.post(
    "/teams/{team_id}/announcements",
    response_model=TeamAnnouncementRead,
    status_code=201,
)
async def create_team_announcement(
    team_id: UUID,
    payload: TeamAnnouncementCreate,
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
    current_user: User = Depends(get_current_active_verified_user),
    session: AsyncSession = Depends(get_db_session),
):
    service = TeamAnnouncementService(session)

    if not idempotency_key:
        announcement = await service.create(
            team_id, current_user, title=payload.title, content=payload.content, is_pinned=payload.is_pinned
        )
        return TeamAnnouncementRead.model_validate(announcement)

    idempotency_service = IdempotencyService(session)
    async with idempotency_service.begin(
        scope="team.announcement.create",
        key=idempotency_key,
        user_id=current_user.id,
        payload={"team_id": str(team_id), **payload.model_dump(mode="json")},
    ) as guard:
        if guard.replayed:
            return JSONResponse(status_code=guard.response_status_code, content=guard.response_body)

        announcement = await service.create(
            team_id, current_user, title=payload.title, content=payload.content, is_pinned=payload.is_pinned
        )
        result = TeamAnnouncementRead.model_validate(announcement)
        body = result.model_dump(mode="json")
        await guard.complete(status_code=201, body=body)
        await session.commit()
        return result


@router.get("/teams/{team_id}/announcements", response_model=PaginatedTeamAnnouncements)
async def list_team_announcements(
    team_id: UUID,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    pinned_only: bool = Query(False),
    sort_order: str = Query("desc", pattern="^(?i)(asc|desc)$"),
    session: AsyncSession = Depends(get_db_session),
):
    service = TeamAnnouncementService(session)
    items, total = await service.list_for_team(
        team_id, page=page, page_size=page_size, pinned_only=pinned_only, sort_order=sort_order
    )
    return PaginatedTeamAnnouncements(
        items=[TeamAnnouncementRead.model_validate(a) for a in items],
        total=total,
        page=page,
        page_size=page_size,
        total_pages=_total_pages(total, page_size),
    )


@router.patch("/teams/{team_id}/announcements/{announcement_id}", response_model=TeamAnnouncementRead)
async def update_team_announcement(
    team_id: UUID,
    announcement_id: UUID,
    payload: TeamAnnouncementUpdate,
    current_user: User = Depends(get_current_active_verified_user),
    session: AsyncSession = Depends(get_db_session),
):
    service = TeamAnnouncementService(session)
    announcement = await service.update(
        team_id,
        announcement_id,
        current_user,
        title=payload.title,
        content=payload.content,
        is_pinned=payload.is_pinned,
    )
    return TeamAnnouncementRead.model_validate(announcement)


@router.delete("/teams/{team_id}/announcements/{announcement_id}", status_code=204)
async def delete_team_announcement(
    team_id: UUID,
    announcement_id: UUID,
    current_user: User = Depends(get_current_active_verified_user),
    session: AsyncSession = Depends(get_db_session),
):
    service = TeamAnnouncementService(session)
    await service.delete(team_id, announcement_id, current_user)


# ----------------------------------------------------------------------
# Team Activity Feed / Member History / Event History
# ----------------------------------------------------------------------
@router.get("/teams/{team_id}/feed", response_model=PaginatedTeamActivityFeed)
async def get_team_activity_feed(
    team_id: UUID,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    activity_type: Optional[TeamActivityType] = Query(None),
    actor_id: Optional[UUID] = Query(None),
    sort_order: str = Query("desc", pattern="^(?i)(asc|desc)$"),
    session: AsyncSession = Depends(get_db_session),
):
    service = TeamActivityFeedService(session)
    items, total = await service.get_feed(
        team_id,
        page=page,
        page_size=page_size,
        activity_type=activity_type,
        actor_id=actor_id,
        sort_order=sort_order,
    )
    return PaginatedTeamActivityFeed(
        items=[TeamActivityFeedEntryRead.model_validate(i) for i in items],
        total=total,
        page=page,
        page_size=page_size,
        total_pages=_total_pages(total, page_size),
    )


@router.get("/teams/{team_id}/members/history", response_model=PaginatedTeamActivityFeed)
async def get_team_member_history(
    team_id: UUID,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    sort_order: str = Query("desc", pattern="^(?i)(asc|desc)$"),
    session: AsyncSession = Depends(get_db_session),
):
    service = TeamActivityFeedService(session)
    items, total = await service.get_member_history(
        team_id, page=page, page_size=page_size, sort_order=sort_order
    )
    return PaginatedTeamActivityFeed(
        items=[TeamActivityFeedEntryRead.model_validate(i) for i in items],
        total=total,
        page=page,
        page_size=page_size,
        total_pages=_total_pages(total, page_size),
    )


@router.get("/teams/{team_id}/events/history", response_model=PaginatedTeamActivityFeed)
async def get_team_event_history(
    team_id: UUID,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    sort_order: str = Query("desc", pattern="^(?i)(asc|desc)$"),
    session: AsyncSession = Depends(get_db_session),
):
    service = TeamActivityFeedService(session)
    items, total = await service.get_event_history(
        team_id, page=page, page_size=page_size, sort_order=sort_order
    )
    return PaginatedTeamActivityFeed(
        items=[TeamActivityFeedEntryRead.model_validate(i) for i in items],
        total=total,
        page=page,
        page_size=page_size,
        total_pages=_total_pages(total, page_size),
    )
