"""
Support chat REST routes -- session bootstrap/history for the user side,
and inbox listing/detail for admins. Actual live messaging happens over
the WebSocket routes; these endpoints exist so a fresh page load can
render current state before the socket connects, and as a fallback for
clients that can't hold a socket open.
"""
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.session import get_db_session
from app.dependencies.auth import get_current_active_verified_user, require_admin
from app.models.support_chat import SupportChatClosedBy, SupportChatStatus
from app.models.user import User
from app.schemas.support_chat import (
    PaginatedSupportChatSessions,
    SupportChatSendMessageRequest,
    SupportChatSessionRead,
    SupportChatSessionWithMessages,
)
from app.services.support_chat_service import SupportChatService

router = APIRouter(tags=["Support Chat"])


# ----------------------------------------------------------------------
# User side
# ----------------------------------------------------------------------
@router.get("/support/session", response_model=SupportChatSessionWithMessages)
async def get_my_support_session(
    current_user: User = Depends(get_current_active_verified_user),
    session: AsyncSession = Depends(get_db_session),
):
    """Returns the user's open session (creating one if none exists) plus
    its full transcript so the support screen can render immediately,
    before the WebSocket connects."""
    service = SupportChatService(session)
    chat_session = await service.get_or_create_open_session(current_user)
    messages = await service.get_history(chat_session)
    return SupportChatSessionWithMessages(
        **SupportChatSessionRead.model_validate(chat_session).model_dump(),
        messages=messages,
    )


@router.post("/support/session/{session_id}/messages", response_model=SupportChatSessionWithMessages)
async def send_support_message(
    session_id: UUID,
    payload: SupportChatSendMessageRequest,
    current_user: User = Depends(get_current_active_verified_user),
    session: AsyncSession = Depends(get_db_session),
):
    """REST fallback for sending a message when the WebSocket isn't
    connected. Returns the refreshed session + transcript."""
    service = SupportChatService(session)
    chat_session = await service.get_session_or_404(session_id)
    await service.post_user_message(current_user, chat_session, payload.content)
    chat_session = await service.get_session_or_404(session_id)
    messages = await service.get_history(chat_session)
    return SupportChatSessionWithMessages(
        **SupportChatSessionRead.model_validate(chat_session).model_dump(),
        messages=messages,
    )


@router.post("/support/session/{session_id}/end", response_model=SupportChatSessionRead)
async def end_my_support_session(
    session_id: UUID,
    current_user: User = Depends(get_current_active_verified_user),
    session: AsyncSession = Depends(get_db_session),
):
    service = SupportChatService(session)
    chat_session = await service.get_session_or_404(session_id)
    chat_session = await service.end_session(current_user, chat_session, SupportChatClosedBy.USER)
    return SupportChatSessionRead.model_validate(chat_session)


# ----------------------------------------------------------------------
# Admin side
# ----------------------------------------------------------------------
@router.get("/admin/support/sessions", response_model=PaginatedSupportChatSessions)
async def admin_list_support_sessions(
    status_filter: Optional[SupportChatStatus] = Query(None, alias="status"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    _admin: User = Depends(require_admin),
    session: AsyncSession = Depends(get_db_session),
):
    service = SupportChatService(session)
    items, total, total_pages = await service.list_for_admin(status_filter, page, page_size)
    return PaginatedSupportChatSessions(
        items=[SupportChatSessionRead.model_validate(s) for s in items],
        total=total,
        page=page,
        page_size=page_size,
        total_pages=total_pages,
    )


@router.get("/admin/support/sessions/{session_id}", response_model=SupportChatSessionWithMessages)
async def admin_get_support_session(
    session_id: UUID,
    _admin: User = Depends(require_admin),
    session: AsyncSession = Depends(get_db_session),
):
    service = SupportChatService(session)
    chat_session = await service.get_session_or_404(session_id)
    messages = await service.get_history(chat_session)
    return SupportChatSessionWithMessages(
        **SupportChatSessionRead.model_validate(chat_session).model_dump(),
        messages=messages,
    )


@router.post("/admin/support/sessions/{session_id}/join", response_model=SupportChatSessionRead)
async def admin_join_support_session(
    session_id: UUID,
    admin: User = Depends(require_admin),
    session: AsyncSession = Depends(get_db_session),
):
    """REST fallback for joining -- normally joining happens implicitly
    when the agent opens the /ws/support/agent/{id} socket, but this lets
    the admin UI mark itself as owner before the socket is up."""
    service = SupportChatService(session)
    chat_session = await service.get_session_or_404(session_id)
    chat_session = await service.join_session(admin, chat_session)
    return SupportChatSessionRead.model_validate(chat_session)


@router.post("/admin/support/sessions/{session_id}/end", response_model=SupportChatSessionRead)
async def admin_end_support_session(
    session_id: UUID,
    admin: User = Depends(require_admin),
    session: AsyncSession = Depends(get_db_session),
):
    service = SupportChatService(session)
    chat_session = await service.get_session_or_404(session_id)
    chat_session = await service.end_session(admin, chat_session, SupportChatClosedBy.AGENT)
    return SupportChatSessionRead.model_validate(chat_session)
