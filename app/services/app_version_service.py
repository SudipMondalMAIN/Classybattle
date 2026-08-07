"""
AppVersion service — admin upsert + the splash-screen check logic.
"""
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundException
from app.models.app_version import AppPlatform, AppVersion
from app.repositories.app_version_repository import AppVersionRepository
from app.schemas.app_version import AppVersionCheckResponse, AppVersionUpsert


def _parse_version(version: str) -> tuple[int, ...]:
    """'1.2.10' -> (1, 2, 10). Non-numeric/missing parts default to 0."""
    parts = []
    for chunk in version.strip().split("."):
        digits = "".join(ch for ch in chunk if ch.isdigit())
        parts.append(int(digits) if digits else 0)
    return tuple(parts)


def _version_lt(a: str, b: str) -> bool:
    """True if version a < version b."""
    pa, pb = _parse_version(a), _parse_version(b)
    length = max(len(pa), len(pb))
    pa = pa + (0,) * (length - len(pa))
    pb = pb + (0,) * (length - len(pb))
    return pa < pb


class AppVersionService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repo = AppVersionRepository(session)

    async def upsert(self, platform: AppPlatform, payload: AppVersionUpsert) -> AppVersion:
        existing = await self.repo.get_by_platform(platform)
        if existing is None:
            return await self.repo.create(platform=platform, **payload.model_dump())
        return await self.repo.update(existing, **payload.model_dump())

    async def get(self, platform: AppPlatform) -> AppVersion:
        record = await self.repo.get_by_platform(platform)
        if record is None:
            raise NotFoundException(f"No version config found for platform '{platform.value}'")
        return record

    async def check(self, platform: AppPlatform, current_version: str) -> AppVersionCheckResponse:
        record = await self.repo.get_by_platform(platform)
        if record is None or not record.is_active:
            # No config yet -- tell the app there's nothing to do rather than error.
            return AppVersionCheckResponse(
                update_available=False,
                force_update=False,
                latest_version=current_version,
                update_url="",
                update_title="",
                update_message="",
            )

        below_min = _version_lt(current_version, record.min_supported_version)
        update_available = _version_lt(current_version, record.latest_version)
        force = record.force_update or below_min

        return AppVersionCheckResponse(
            update_available=update_available,
            force_update=force and update_available,
            latest_version=record.latest_version,
            update_url=record.update_url,
            update_title=record.update_title,
            update_message=record.update_message,
        )
