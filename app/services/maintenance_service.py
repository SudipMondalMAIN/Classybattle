"""
Maintenance service — admin toggle + the splash-screen check, completely
separate from AppVersionService/force-update.
"""
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.maintenance import MaintenanceConfig
from app.repositories.maintenance_repository import MaintenanceRepository
from app.schemas.maintenance import MaintenanceCheckResponse, MaintenanceUpsert


class MaintenanceService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repo = MaintenanceRepository(session)

    async def get_or_create(self) -> MaintenanceConfig:
        record = await self.repo.get_singleton()
        if record is not None:
            return record
        record = await self.repo.create(is_enabled=False)
        await self.session.commit()
        return record

    async def check(self) -> MaintenanceCheckResponse:
        """Called from the splash screen. Cheap, public, no auth."""
        record = await self.repo.get_singleton()
        if record is None or not record.is_enabled:
            return MaintenanceCheckResponse(
                is_enabled=False, title="", message="", status_url=""
            )
        return MaintenanceCheckResponse(
            is_enabled=True,
            title=record.title,
            message=record.message,
            status_url=record.status_url,
        )

    async def upsert(self, payload: MaintenanceUpsert) -> MaintenanceConfig:
        """Admin on/off toggle. Fields left blank (None) keep whatever was
        previously configured -- an admin flipping maintenance back on
        doesn't have to retype the title/message/status_url every time."""
        record = await self.get_or_create()
        updates: dict = {"is_enabled": payload.is_enabled}
        if payload.title is not None:
            updates["title"] = payload.title
        if payload.message is not None:
            updates["message"] = payload.message
        if payload.status_url is not None:
            updates["status_url"] = payload.status_url

        record = await self.repo.update(record, **updates)
        await self.session.commit()
        return record
