"""
Banner service — admin create/list/update/delete + direct image upload.
"""
from typing import Sequence
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundException, ValidationException
from app.models.banner import Banner
from app.repositories.banner_repository import BannerRepository
from app.schemas.banner import BannerCreate, BannerUpdate
from app.storage.storage_service import StorageService

_ALLOWED_IMAGE_CONTENT_TYPES = {"image/jpeg", "image/png", "image/webp"}
_MAX_IMAGE_SIZE_BYTES = 5 * 1024 * 1024  # 5 MB


class BannerService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repo = BannerRepository(session)
        self.storage = StorageService(bucket="banner-assets")

    def _validate_asset(self, content_type: str, file_bytes: bytes) -> None:
        if content_type not in _ALLOWED_IMAGE_CONTENT_TYPES:
            raise ValidationException(
                "Only JPEG, PNG or WEBP images are allowed for banners"
            )
        if len(file_bytes) > _MAX_IMAGE_SIZE_BYTES:
            raise ValidationException("Banner image must be 5 MB or smaller")

    async def get_by_id(self, banner_id: UUID) -> Banner:
        banner = await self.repo.get_by_id(banner_id)
        if banner is None:
            raise NotFoundException("Banner not found")
        return banner

    async def list_active(self) -> Sequence[Banner]:
        """Public: banners shown on the home screen."""
        return await self.repo.list_active()

    async def list_all_for_admin(self) -> Sequence[Banner]:
        return await self.repo.list_all_for_admin()

    async def create_banner(
        self,
        payload: BannerCreate,
        file_bytes: bytes,
        content_type: str,
    ) -> Banner:
        """Admin creates a banner via direct image upload; title/link optional."""
        self._validate_asset(content_type, file_bytes)

        extension = content_type.split("/")[-1]
        path = f"banners/{uuid4().hex}-{uuid4().hex[:8]}.{extension}"
        url = await self.storage.upload_file(path, file_bytes, content_type)

        banner = await self.repo.create(image_url=url, **payload.model_dump())
        await self.session.commit()
        return banner

    async def update_banner(self, banner_id: UUID, payload: BannerUpdate) -> Banner:
        banner = await self.get_by_id(banner_id)
        update_data = payload.model_dump(exclude_unset=True)
        banner = await self.repo.update(banner, **update_data)
        await self.session.commit()
        return banner

    async def replace_image(
        self, banner_id: UUID, file_bytes: bytes, content_type: str
    ) -> Banner:
        banner = await self.get_by_id(banner_id)
        self._validate_asset(content_type, file_bytes)

        extension = content_type.split("/")[-1]
        path = f"banners/{banner.id}-{uuid4().hex[:8]}.{extension}"
        url = await self.storage.upload_file(path, file_bytes, content_type)

        banner = await self.repo.update(banner, image_url=url)
        await self.session.commit()
        return banner

    async def delete_banner(self, banner_id: UUID) -> None:
        """Remove a banner (soft delete — also drops it from the public list)."""
        banner = await self.get_by_id(banner_id)
        await self.repo.soft_delete(banner)
        await self.session.commit()
