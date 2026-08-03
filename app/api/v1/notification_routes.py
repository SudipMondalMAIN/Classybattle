"""
Notification API routes — Phase 13 (Enterprise Notification & Communication System).
"""
import uuid
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundException
from app.database.session import get_db_session
from app.dependencies.auth import get_current_active_verified_user, require_admin
from app.models.notification import NotificationEventType
from app.models.user import User
from app.schemas.notification import (
    AdminBroadcastRequest,
    AdminBroadcastResponse,
    BulkDeleteRequest,
    BulkDeleteResponse,
    DeviceTokenDeregisterRequest,
    DeviceTokenRegisterRequest,
    MarkReadResponse,
    NotificationPreferenceRead,
    NotificationPreferenceUpdate,
    NotificationRead,
    PaginatedNotifications,
    UnreadCountResponse,
)
from app.services.idempotency_service import IdempotencyService
from app.services.notification_service import NotificationService

router = APIRouter(tags=["Notifications"])


# ----------------------------------------------------------------------
# Current user's notifications
# ----------------------------------------------------------------------
@router.get("/notifications", response_model=PaginatedNotifications)
async def list_my_notifications(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    is_read: Optional[bool] = Query(None),
    event_type: Optional[NotificationEventType] = Query(None),
    sort_by: str = Query("created_at"),
    sort_order: str = Query("desc", pattern="^(?i)(asc|desc)$"),
    current_user: User = Depends(get_current_active_verified_user),
    session: AsyncSession = Depends(get_db_session),
):
    service = NotificationService(session)
    items, total, total_pages = await service.list_for_user(
        current_user,
        page=page,
        page_size=page_size,
        is_read=is_read,
        event_type=event_type,
        sort_by=sort_by,
        sort_order=sort_order,
    )
    return PaginatedNotifications(
        items=[NotificationRead.model_validate(n) for n in items],
        total=total,
        page=page,
        page_size=page_size,
        total_pages=total_pages,
    )


@router.get("/notifications/unread-count", response_model=UnreadCountResponse)
async def get_unread_count(
    current_user: User = Depends(get_current_active_verified_user),
    session: AsyncSession = Depends(get_db_session),
):
    service = NotificationService(session)
    count = await service.get_unread_count(current_user)
    return UnreadCountResponse(unread_count=count)


@router.patch("/notifications/read-all", response_model=MarkReadResponse)
async def mark_all_read(
    current_user: User = Depends(get_current_active_verified_user),
    session: AsyncSession = Depends(get_db_session),
):
    service = NotificationService(session)
    count = await service.mark_all_read(current_user)
    return MarkReadResponse(marked=count)


@router.patch("/notifications/{notification_id}/read", response_model=NotificationRead)
async def mark_notification_read(
    notification_id: UUID,
    current_user: User = Depends(get_current_active_verified_user),
    session: AsyncSession = Depends(get_db_session),
):
    service = NotificationService(session)
    notification = await service.mark_read(current_user, notification_id)
    return NotificationRead.model_validate(notification)


# ----------------------------------------------------------------------
# Device tokens (push)
#
# NOTE: registered here, ABOVE the dynamic delete("/notifications/{id}")
# route below. FastAPI/Starlette matches routes in registration order,
# so DELETE /notifications/device-tokens would otherwise be captured by
# delete("/notifications/{notification_id}") with
# notification_id="device-tokens", failing UUID parsing (422).
# ----------------------------------------------------------------------
@router.post("/notifications/device-tokens", status_code=201)
async def register_device_token(
    payload: DeviceTokenRegisterRequest,
    current_user: User = Depends(get_current_active_verified_user),
    session: AsyncSession = Depends(get_db_session),
):
    service = NotificationService(session)
    await service.register_device_token(current_user, payload.fcm_token, payload.platform)
    return {"success": True}


@router.delete("/notifications/device-tokens")
async def deregister_device_token(
    payload: DeviceTokenDeregisterRequest,
    current_user: User = Depends(get_current_active_verified_user),
    session: AsyncSession = Depends(get_db_session),
):
    service = NotificationService(session)
    removed = await service.deregister_device_token(current_user, payload.fcm_token)
    return {"success": removed}


@router.delete("/notifications/{notification_id}", response_model=MarkReadResponse)
async def delete_notification(
    notification_id: UUID,
    current_user: User = Depends(get_current_active_verified_user),
    session: AsyncSession = Depends(get_db_session),
):
    service = NotificationService(session)
    await service.delete(current_user, notification_id)
    return MarkReadResponse(marked=1)


@router.post("/notifications/bulk-delete", response_model=BulkDeleteResponse)
async def bulk_delete_notifications(
    payload: BulkDeleteRequest,
    current_user: User = Depends(get_current_active_verified_user),
    session: AsyncSession = Depends(get_db_session),
):
    service = NotificationService(session)
    deleted = await service.bulk_delete(current_user, payload.notification_ids)
    return BulkDeleteResponse(deleted=deleted)


# ----------------------------------------------------------------------
# Preferences
# ----------------------------------------------------------------------
@router.get("/notifications/preferences", response_model=NotificationPreferenceRead)
async def get_my_preferences(
    current_user: User = Depends(get_current_active_verified_user),
    session: AsyncSession = Depends(get_db_session),
):
    service = NotificationService(session)
    pref = await service.get_preferences(current_user)
    return NotificationPreferenceRead.model_validate(pref)


@router.put("/notifications/preferences", response_model=NotificationPreferenceRead)
async def update_my_preferences(
    payload: NotificationPreferenceUpdate,
    current_user: User = Depends(get_current_active_verified_user),
    session: AsyncSession = Depends(get_db_session),
):
    service = NotificationService(session)
    pref = await service.update_preferences(current_user, payload)
    return NotificationPreferenceRead.model_validate(pref)


# ----------------------------------------------------------------------
# Admin
# ----------------------------------------------------------------------
@router.get("/admin/notifications", response_model=PaginatedNotifications)
async def admin_list_notifications(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    user_id: Optional[UUID] = Query(None),
    event_type: Optional[NotificationEventType] = Query(None),
    sort_by: str = Query("created_at"),
    sort_order: str = Query("desc", pattern="^(?i)(asc|desc)$"),
    _admin: User = Depends(require_admin),
    session: AsyncSession = Depends(get_db_session),
):
    service = NotificationService(session)
    items, total, total_pages = await service.list_for_admin(
        page=page,
        page_size=page_size,
        user_id=user_id,
        event_type=event_type,
        sort_by=sort_by,
        sort_order=sort_order,
    )
    return PaginatedNotifications(
        items=[NotificationRead.model_validate(n) for n in items],
        total=total,
        page=page,
        page_size=page_size,
        total_pages=total_pages,
    )


@router.get("/admin/notifications/{notification_id}", response_model=NotificationRead)
async def admin_get_notification(
    notification_id: UUID,
    _admin: User = Depends(require_admin),
    session: AsyncSession = Depends(get_db_session),
):
    from app.repositories.notification_repository import NotificationRepository

    repo = NotificationRepository(session)
    notification = await repo.get_by_id(notification_id, include_deleted=True)
    if notification is None:
        raise NotFoundException("Notification not found")
    return NotificationRead.model_validate(notification)


@router.post("/admin/notifications/broadcast", response_model=AdminBroadcastResponse)
async def admin_broadcast_notification(
    payload: AdminBroadcastRequest,
    admin: User = Depends(require_admin),
    session: AsyncSession = Depends(get_db_session),
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
):
    service = NotificationService(session)
    broadcast_id = uuid.uuid4()

    if idempotency_key:
        idem = IdempotencyService(session)
        async with idem.begin(
            scope="notifications.broadcast",
            key=idempotency_key,
            user_id=admin.id,
            payload=payload.model_dump(mode="json"),
        ) as guard:
            if guard.replayed:
                return AdminBroadcastResponse(**guard.response_body)
            recipients = await service.admin_broadcast(
                admin=admin,
                title=payload.title,
                body=payload.body,
                target_user_ids=payload.target_user_ids,
                send_push=payload.send_push,
                send_email=payload.send_email,
                broadcast_id=broadcast_id,
            )
            response = AdminBroadcastResponse(recipients=recipients)
            await guard.complete(status_code=200, body=response.model_dump(mode="json"))
            return response

    recipients = await service.admin_broadcast(
        admin=admin,
        title=payload.title,
        body=payload.body,
        target_user_ids=payload.target_user_ids,
        send_push=payload.send_push,
        send_email=payload.send_email,
        broadcast_id=broadcast_id,
    )
    return AdminBroadcastResponse(recipients=recipients)
