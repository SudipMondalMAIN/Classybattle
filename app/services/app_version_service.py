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
            record = await self.repo.create(platform=platform, **payload.model_dump())
        else:
            record = await self.repo.update(existing, **payload.model_dump())
        await self.session.commit()
        return record

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

        if record.maintenance_mode:
            # Kill-switch: block every installed version regardless of its
            # number, no need to fake latest_version/min_supported_version.
            return AppVersionCheckResponse(
                update_available=True,
                force_update=True,
                latest_version=record.latest_version,
                update_url=record.update_url,
                update_title=record.update_title,
                update_message=record.update_message,
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

    async def set_maintenance(
        self,
        platform: AppPlatform,
        *,
        enabled: bool,
        title: str | None = None,
        message: str | None = None,
        status_url: str | None = None,
    ) -> AppVersion:
        """Dedicated on/off switch for the maintenance kill-switch. Creates
        a minimal AppVersion row for the platform if one doesn't exist yet
        (e.g. version info was never configured), since maintenance_mode
        must work independently of that setup."""
        record = await self.repo.get_by_platform(platform)
        updates: dict = {"maintenance_mode": enabled, "is_active": True}
        if title is not None:
            updates["update_title"] = title
        if message is not None:
            updates["update_message"] = message
        if status_url is not None:
            updates["update_url"] = status_url

        if record is None:
            defaults = {
                "latest_version": "0.0.0",
                "latest_build_number": 1,
                "min_supported_version": "0.0.0",
                "force_update": False,
                "update_url": status_url or "https://status.classybattle.online",
                "update_title": title or "Under Maintenance",
                "update_message": message
                or "ClassyBattle is currently undergoing scheduled maintenance. Please check back shortly.",
            }
            defaults.update(updates)
            record = await self.repo.create(platform=platform, **defaults)
        else:
            record = await self.repo.update(record, **updates)

        await self.session.commit()
        return record