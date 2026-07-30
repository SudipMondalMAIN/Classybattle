"""
Game Mode service — validation, slug management, and orchestration between
the repository layer and the Game catalogue (Phase 3).
"""
from typing import Optional
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictException, NotFoundException, ValidationException
from app.models.game_mode import GameMode
from app.models.user import User
from app.repositories.game_mode_repository import GameModeRepository
from app.repositories.game_repository import GameRepository
from app.schemas.game_mode import GameModeCreate, GameModeUpdate
from app.utils.slug import generate_unique_suffix, slugify


class GameModeService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repo = GameModeRepository(session)
        self.game_repo = GameRepository(session)

    # ------------------------------------------------------------------
    # Slug helpers
    # ------------------------------------------------------------------
    async def _generate_unique_slug(
        self, game_id: UUID, name: str, exclude_id: Optional[UUID] = None
    ) -> str:
        base = slugify(name)
        candidate = base
        # A handful of attempts with random suffixes comfortably avoids
        # collisions without an unbounded loop.
        for _ in range(5):
            if not await self.repo.slug_exists(game_id, candidate, exclude_id=exclude_id):
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

    @staticmethod
    def _assert_valid_player_limits(
        min_players: int, max_players: int, max_team_size: int
    ) -> None:
        if min_players <= 0:
            raise ValidationException("min_players must be greater than 0")
        if max_players <= 0:
            raise ValidationException("max_players must be greater than 0")
        if max_players < min_players:
            raise ValidationException("max_players cannot be less than min_players")
        if max_team_size <= 0:
            raise ValidationException("max_team_size must be greater than 0")
        if max_team_size > max_players:
            raise ValidationException("max_team_size cannot exceed max_players")

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------
    async def create_mode(self, payload: GameModeCreate, current_user: User) -> GameMode:
        await self._assert_game_exists(payload.game_id)
        self._assert_valid_player_limits(
            payload.min_players, payload.max_players, payload.max_team_size
        )

        if await self.repo.name_exists(payload.game_id, payload.name):
            raise ConflictException(
                "A game mode with this name already exists for this game"
            )

        slug = await self._generate_unique_slug(payload.game_id, payload.name)

        mode = await self.repo.create(
            game_id=payload.game_id,
            name=payload.name,
            slug=slug,
            short_name=payload.short_name,
            description=payload.description,
            icon_url=payload.icon_url,
            image_url=payload.image_url,
            max_team_size=payload.max_team_size,
            min_players=payload.min_players,
            max_players=payload.max_players,
            sort_order=payload.sort_order,
            is_active=payload.is_active,
            is_featured=payload.is_featured,
            created_by=current_user.id,
            updated_by=current_user.id,
        )
        await self.session.commit()
        return mode

    async def get_by_id(self, mode_id: UUID, include_deleted: bool = False) -> GameMode:
        mode = await self.repo.get_by_id(mode_id, include_deleted=include_deleted)
        if mode is None:
            raise NotFoundException("Game mode not found")
        return mode

    async def get_by_slug(self, game_id: UUID, slug: str) -> GameMode:
        mode = await self.repo.get_by_slug(game_id, slug)
        if mode is None:
            raise NotFoundException("Game mode not found")
        return mode

    async def list_modes(
        self,
        *,
        page: int,
        page_size: int,
        game_id: Optional[UUID],
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
            is_active=is_active,
            is_featured=is_featured,
            search=search,
            sort_by=sort_by,
            sort_order=sort_order,
        )

    async def update_mode(
        self, mode_id: UUID, payload: GameModeUpdate, current_user: User
    ) -> GameMode:
        mode = await self.get_by_id(mode_id)

        update_data = payload.model_dump(exclude_unset=True)

        if "name" in update_data and update_data["name"] != mode.name:
            if await self.repo.name_exists(mode.game_id, update_data["name"], exclude_id=mode.id):
                raise ConflictException(
                    "A game mode with this name already exists for this game"
                )
            update_data["slug"] = await self._generate_unique_slug(
                mode.game_id, update_data["name"], exclude_id=mode.id
            )

        min_players = update_data.get("min_players", mode.min_players)
        max_players = update_data.get("max_players", mode.max_players)
        max_team_size = update_data.get("max_team_size", mode.max_team_size)
        self._assert_valid_player_limits(min_players, max_players, max_team_size)

        update_data["updated_by"] = current_user.id

        mode = await self.repo.update(mode, **update_data)
        await self.session.commit()
        return mode

    async def soft_delete_mode(self, mode_id: UUID, current_user: User) -> None:
        mode = await self.get_by_id(mode_id)
        await self.repo.update(mode, updated_by=current_user.id)
        await self.repo.soft_delete(mode)
        await self.session.commit()
