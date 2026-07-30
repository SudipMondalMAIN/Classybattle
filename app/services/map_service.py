"""
Map service — validation, slug management, image uploads, and orchestration
between the repository layer, the Game catalogue, and Game Modes (Phase 4).
"""
from typing import Optional
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictException, NotFoundException, ValidationException
from app.models.map import Map
from app.models.user import User
from app.repositories.game_mode_repository import GameModeRepository
from app.repositories.game_repository import GameRepository
from app.repositories.map_repository import MapRepository
from app.schemas.map import MapCreate, MapUpdate
from app.storage.storage_service import StorageService
from app.utils.slug import generate_unique_suffix, slugify

# Asset upload constraints for map image/thumbnail.
_ALLOWED_IMAGE_CONTENT_TYPES = {"image/jpeg", "image/png", "image/webp"}
_MAX_IMAGE_SIZE_BYTES = 5 * 1024 * 1024  # 5 MB


class MapService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repo = MapRepository(session)
        self.game_repo = GameRepository(session)
        self.mode_repo = GameModeRepository(session)
        self.storage = StorageService(bucket="map-assets")

    # ------------------------------------------------------------------
    # Slug helpers
    # ------------------------------------------------------------------
    async def _generate_unique_slug(
        self,
        game_id: UUID,
        mode_id: Optional[UUID],
        name: str,
        exclude_id: Optional[UUID] = None,
    ) -> str:
        base = slugify(name)
        candidate = base
        # A handful of attempts with random suffixes comfortably avoids
        # collisions without an unbounded loop.
        for _ in range(5):
            if not await self.repo.slug_exists(game_id, mode_id, candidate, exclude_id=exclude_id):
                return candidate
            candidate = f"{base}-{generate_unique_suffix()}"
        # Extremely unlikely fallback: fully random suffix guarantees uniqueness.
        return f"{base}-{uuid4().hex[:10]}"

    # ------------------------------------------------------------------
    # Validation helpers
    # ------------------------------------------------------------------
    async def _assert_game_exists(self, game_id: UUID) -> None:
        game = await self.game_repo.get_by_id(game_id)
        if game is None:
            raise ValidationException("Invalid game: game does not exist")
        if not game.is_active:
            raise ValidationException("Invalid game: game is not active")

    async def _assert_mode_valid(self, game_id: UUID, mode_id: Optional[UUID]) -> None:
        if mode_id is None:
            return
        mode = await self.mode_repo.get_by_id(mode_id)
        if mode is None:
            raise ValidationException("Invalid mode: game mode does not exist")
        if mode.game_id != game_id:
            raise ValidationException("Invalid mode: game mode does not belong to this game")

    @staticmethod
    def _validate_asset(content_type: str, file_bytes: bytes) -> None:
        if content_type not in _ALLOWED_IMAGE_CONTENT_TYPES:
            raise ValidationException(
                "Unsupported file type. Allowed types: JPEG, PNG, WEBP"
            )
        if len(file_bytes) > _MAX_IMAGE_SIZE_BYTES:
            raise ValidationException("File is too large. Maximum size is 5 MB")
        if len(file_bytes) == 0:
            raise ValidationException("Uploaded file is empty")

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------
    async def create_map(self, payload: MapCreate, current_user: User) -> Map:
        await self._assert_game_exists(payload.game_id)
        await self._assert_mode_valid(payload.game_id, payload.mode_id)

        if await self.repo.name_exists(payload.game_id, payload.mode_id, payload.name):
            raise ConflictException(
                "A map with this name already exists for this game/mode"
            )

        slug = await self._generate_unique_slug(payload.game_id, payload.mode_id, payload.name)

        map_ = await self.repo.create(
            game_id=payload.game_id,
            mode_id=payload.mode_id,
            name=payload.name,
            slug=slug,
            short_name=payload.short_name,
            description=payload.description,
            image_url=payload.image_url,
            thumbnail_url=payload.thumbnail_url,
            sort_order=payload.sort_order,
            is_active=payload.is_active,
            is_featured=payload.is_featured,
            created_by=current_user.id,
            updated_by=current_user.id,
        )
        await self.session.commit()
        return map_

    async def get_by_id(self, map_id: UUID, include_deleted: bool = False) -> Map:
        map_ = await self.repo.get_by_id(map_id, include_deleted=include_deleted)
        if map_ is None:
            raise NotFoundException("Map not found")
        return map_

    async def get_by_slug(self, game_id: UUID, slug: str) -> Map:
        map_ = await self.repo.get_by_slug(game_id, slug)
        if map_ is None:
            raise NotFoundException("Map not found")
        return map_

    async def list_maps(
        self,
        *,
        page: int,
        page_size: int,
        game_id: Optional[UUID],
        mode_id: Optional[UUID],
        is_active: Optional[bool],
        is_featured: Optional[bool],
        search: Optional[str],
        sort_by: str,
        sort_order: str,
    ):
        return await self.repo.list_paginated(
            page=page,
            page_size=page_size,
            game_id=game_id,
            mode_id=mode_id,
            is_active=is_active,
            is_featured=is_featured,
            search=search,
            sort_by=sort_by,
            sort_order=sort_order,
        )

    async def update_map(self, map_id: UUID, payload: MapUpdate, current_user: User) -> Map:
        map_ = await self.get_by_id(map_id)

        update_data = payload.model_dump(exclude_unset=True)

        target_mode_id = update_data.get("mode_id", map_.mode_id)
        if "mode_id" in update_data:
            await self._assert_mode_valid(map_.game_id, target_mode_id)

        if "name" in update_data and (
            update_data["name"] != map_.name or target_mode_id != map_.mode_id
        ):
            if await self.repo.name_exists(
                map_.game_id, target_mode_id, update_data["name"], exclude_id=map_.id
            ):
                raise ConflictException(
                    "A map with this name already exists for this game/mode"
                )
            update_data["slug"] = await self._generate_unique_slug(
                map_.game_id, target_mode_id, update_data["name"], exclude_id=map_.id
            )
        elif "mode_id" in update_data and target_mode_id != map_.mode_id:
            if await self.repo.slug_exists(
                map_.game_id, target_mode_id, map_.slug, exclude_id=map_.id
            ):
                update_data["slug"] = await self._generate_unique_slug(
                    map_.game_id, target_mode_id, map_.name, exclude_id=map_.id
                )

        update_data["updated_by"] = current_user.id

        map_ = await self.repo.update(map_, **update_data)
        await self.session.commit()
        return map_

    async def soft_delete_map(self, map_id: UUID, current_user: User) -> None:
        map_ = await self.get_by_id(map_id)
        await self.repo.update(map_, updated_by=current_user.id)
        await self.repo.soft_delete(map_)
        await self.session.commit()

    # ------------------------------------------------------------------
    # Asset uploads
    # ------------------------------------------------------------------
    async def upload_image(
        self,
        map_id: UUID,
        file_bytes: bytes,
        content_type: str,
        current_user: User,
    ) -> Map:
        map_ = await self.get_by_id(map_id)
        self._validate_asset(content_type, file_bytes)

        extension = content_type.split("/")[-1]
        path = f"maps/{map_.id}/image-{uuid4().hex[:8]}.{extension}"
        url = await self.storage.upload_file(path, file_bytes, content_type)

        map_ = await self.repo.update(map_, image_url=url, updated_by=current_user.id)
        await self.session.commit()
        return map_

    async def upload_thumbnail(
        self,
        map_id: UUID,
        file_bytes: bytes,
        content_type: str,
        current_user: User,
    ) -> Map:
        map_ = await self.get_by_id(map_id)
        self._validate_asset(content_type, file_bytes)

        extension = content_type.split("/")[-1]
        path = f"maps/{map_.id}/thumbnail-{uuid4().hex[:8]}.{extension}"
        url = await self.storage.upload_file(path, file_bytes, content_type)

        map_ = await self.repo.update(map_, thumbnail_url=url, updated_by=current_user.id)
        await self.session.commit()
        return map_
