"""
HomeCategoryBox service — admin create/list/update/delete for the
home-screen category boxes (Solo / Squad / Custom).
"""
from typing import Sequence
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundException, ValidationException
from app.models.home_category_box import HomeCategoryBox, HomeCategoryBoxType
from app.repositories.game_repository import GameRepository
from app.repositories.home_category_box_repository import HomeCategoryBoxRepository
from app.schemas.home_category_box import HomeCategoryBoxCreate, HomeCategoryBoxUpdate


class HomeCategoryBoxService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repo = HomeCategoryBoxRepository(session)
        self.game_repo = GameRepository(session)

    async def get_by_id(self, box_id: UUID) -> HomeCategoryBox:
        box = await self.repo.get_by_id(box_id)
        if box is None:
            raise NotFoundException("Home category box not found")
        return box

    async def list_active(self) -> Sequence[HomeCategoryBox]:
        """Public: boxes to show on the app home screen, in sort order."""
        return await self.repo.list_active()

    async def list_all_for_admin(self) -> Sequence[HomeCategoryBox]:
        return await self.repo.list_all_for_admin()

    async def _validate_game(self, game_id: UUID) -> None:
        game = await self.game_repo.get_by_id(game_id)
        if game is None:
            raise ValidationException("Selected game does not exist")

    async def create_box(self, payload: HomeCategoryBoxCreate) -> HomeCategoryBox:
        if payload.game_id is not None:
            await self._validate_game(payload.game_id)
        box = await self.repo.create(**payload.model_dump())
        await self.session.commit()
        return box

    async def update_box(self, box_id: UUID, payload: HomeCategoryBoxUpdate) -> HomeCategoryBox:
        box = await self.get_by_id(box_id)
        update_data = payload.model_dump(exclude_unset=True)

        # Resolve what box_type/game_id will be after this update to keep
        # the "custom -> no game, solo/squad -> game required" rule intact
        # even on a partial PATCH.
        new_type = update_data.get("box_type", box.box_type)
        new_game_id = update_data.get("game_id", box.game_id)

        if new_type == HomeCategoryBoxType.CUSTOM:
            update_data["game_id"] = None
        else:
            if new_game_id is None:
                raise ValidationException("game_id is required for solo/squad boxes")
            await self._validate_game(new_game_id)

        box = await self.repo.update(box, **update_data)
        await self.session.commit()
        return box

    async def delete_box(self, box_id: UUID) -> None:
        box = await self.get_by_id(box_id)
        await self.repo.soft_delete(box)
        await self.session.commit()
