"""
Home Category Box routes.

Public: GET /home-boxes -- active boxes for the app home screen (3-per-row
Solo / Squad / Custom tap boxes).
Admin:  full CRUD under /home-boxes/admin/...
"""
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.session import get_db_session
from app.dependencies.auth import require_admin
from app.models.user import User
from app.schemas.common import MessageResponse
from app.schemas.home_category_box import (
    HomeCategoryBoxCreate,
    HomeCategoryBoxRead,
    HomeCategoryBoxUpdate,
)
from app.services.home_category_box_service import HomeCategoryBoxService

router = APIRouter(prefix="/home-boxes", tags=["Home Category Boxes"])


@router.get("", response_model=list[HomeCategoryBoxRead])
async def list_active_boxes(session: AsyncSession = Depends(get_db_session)):
    """Public: home-screen category boxes to show, in sort order."""
    service = HomeCategoryBoxService(session)
    boxes = await service.list_active()
    return [HomeCategoryBoxRead.model_validate(b) for b in boxes]


@router.get("/admin", response_model=list[HomeCategoryBoxRead])
async def list_all_boxes_admin(
    current_user: User = Depends(require_admin),
    session: AsyncSession = Depends(get_db_session),
):
    """Admin: every box (active + inactive) for the admin panel."""
    service = HomeCategoryBoxService(session)
    boxes = await service.list_all_for_admin()
    return [HomeCategoryBoxRead.model_validate(b) for b in boxes]


@router.post("/admin", response_model=HomeCategoryBoxRead, status_code=201)
async def create_box(
    payload: HomeCategoryBoxCreate,
    current_user: User = Depends(require_admin),
    session: AsyncSession = Depends(get_db_session),
):
    """Admin: add a home box — pick type (solo/squad/custom), game (unless
    custom), banner link, optional title, sort order, active flag."""
    service = HomeCategoryBoxService(session)
    box = await service.create_box(payload)
    return HomeCategoryBoxRead.model_validate(box)


@router.patch("/admin/{box_id}", response_model=HomeCategoryBoxRead)
async def update_box(
    box_id: UUID,
    payload: HomeCategoryBoxUpdate,
    current_user: User = Depends(require_admin),
    session: AsyncSession = Depends(get_db_session),
):
    """Admin: edit any field of an existing box."""
    service = HomeCategoryBoxService(session)
    box = await service.update_box(box_id, payload)
    return HomeCategoryBoxRead.model_validate(box)


@router.delete("/admin/{box_id}", response_model=MessageResponse)
async def delete_box(
    box_id: UUID,
    current_user: User = Depends(require_admin),
    session: AsyncSession = Depends(get_db_session),
):
    """Admin: remove a home box."""
    service = HomeCategoryBoxService(session)
    await service.delete_box(box_id)
    return MessageResponse(message="Home category box deleted successfully")
