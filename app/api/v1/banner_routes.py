"""
Banner routes.

Public: GET /banners -- active banners for the app home screen.
Admin:  full CRUD + direct image upload, all under /banners/admin/...
"""
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ValidationException
from app.database.session import get_db_session
from app.dependencies.auth import require_admin
from app.models.user import User
from app.schemas.banner import BannerCreate, BannerRead, BannerUpdate
from app.schemas.common import MessageResponse
from app.services.banner_service import BannerService

router = APIRouter(prefix="/banners", tags=["Banners"])


@router.get("", response_model=list[BannerRead])
async def list_active_banners(session: AsyncSession = Depends(get_db_session)):
    """Public: banners to show on the app home screen, in sort order."""
    service = BannerService(session)
    banners = await service.list_active()
    return [BannerRead.model_validate(b) for b in banners]


@router.get("/admin", response_model=list[BannerRead])
async def list_all_banners_admin(
    current_user: User = Depends(require_admin),
    session: AsyncSession = Depends(get_db_session),
):
    """Admin: every banner (active + inactive) for the admin panel."""
    service = BannerService(session)
    banners = await service.list_all_for_admin()
    return [BannerRead.model_validate(b) for b in banners]


@router.post("/admin", response_model=BannerRead, status_code=201)
async def create_banner(
    file: UploadFile = File(...),
    title: str | None = Form(None),
    redirect_link: str | None = Form(None),
    sort_order: int = Form(0),
    is_active: bool = Form(True),
    current_user: User = Depends(require_admin),
    session: AsyncSession = Depends(get_db_session),
):
    """Admin: add a banner — direct image upload, title/redirect link optional."""
    if file.content_type is None:
        raise ValidationException("File content type is required")
    file_bytes = await file.read()

    payload = BannerCreate(
        title=title,
        redirect_link=redirect_link,
        sort_order=sort_order,
        is_active=is_active,
    )
    service = BannerService(session)
    banner = await service.create_banner(payload, file_bytes, file.content_type)
    return BannerRead.model_validate(banner)


@router.patch("/admin/{banner_id}", response_model=BannerRead)
async def update_banner(
    banner_id: UUID,
    payload: BannerUpdate,
    current_user: User = Depends(require_admin),
    session: AsyncSession = Depends(get_db_session),
):
    """Admin: edit title/redirect link/sort order/active flag."""
    service = BannerService(session)
    banner = await service.update_banner(banner_id, payload)
    return BannerRead.model_validate(banner)


@router.post("/admin/{banner_id}/image", response_model=BannerRead)
async def replace_banner_image(
    banner_id: UUID,
    file: UploadFile = File(...),
    current_user: User = Depends(require_admin),
    session: AsyncSession = Depends(get_db_session),
):
    """Admin: replace just the image of an existing banner."""
    if file.content_type is None:
        raise ValidationException("File content type is required")
    file_bytes = await file.read()
    service = BannerService(session)
    banner = await service.replace_image(banner_id, file_bytes, file.content_type)
    return BannerRead.model_validate(banner)


@router.delete("/admin/{banner_id}", response_model=MessageResponse)
async def delete_banner(
    banner_id: UUID,
    current_user: User = Depends(require_admin),
    session: AsyncSession = Depends(get_db_session),
):
    """Admin: remove a banner."""
    service = BannerService(session)
    await service.delete_banner(banner_id)
    return MessageResponse(message="Banner deleted successfully")
