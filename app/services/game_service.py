"""
Game catalogue + per-user game profile service.
"""
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictException, NotFoundException, ValidationException
from app.models.game import Game
from app.models.game_profile import UserGameProfile
from app.repositories.game_repository import GameRepository, UserGameProfileRepository
from app.schemas.game import GameCreate, GameUpdate, UserGameProfileCreate, UserGameProfileUpdate
from app.utils.slug import generate_unique_suffix, slugify


class GameService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.game_repo = GameRepository(session)
        self.profile_repo = UserGameProfileRepository(session)

    async def list_active_games(self) -> list[Game]:
        return await self.game_repo.list_active()

    async def _generate_unique_slug(self, name: str) -> str:
        base = slugify(name)
        candidate = base
        while await self.game_repo.slug_exists(candidate):
            candidate = f"{base}-{generate_unique_suffix()}"
        return candidate

    async def create_game(self, payload: GameCreate) -> Game:
        if await self.game_repo.name_exists(payload.name):
            raise ConflictException("A game with this name already exists")

        slug = await self._generate_unique_slug(payload.name)
        game = await self.game_repo.create(
            name=payload.name,
            slug=slug,
            icon_url=payload.icon_url,
            is_active=payload.is_active,
            profile_schema=[field.model_dump() for field in payload.profile_schema],
        )
        await self.session.commit()
        return game

    async def update_game(self, game_id: UUID, payload: GameUpdate) -> Game:
        game = await self.game_repo.get_by_id(game_id)
        if game is None:
            raise NotFoundException("Game not found")

        updates: dict = {}
        if payload.name is not None and payload.name != game.name:
            if await self.game_repo.name_exists(payload.name):
                raise ConflictException("A game with this name already exists")
            updates["name"] = payload.name
        if payload.icon_url is not None:
            updates["icon_url"] = payload.icon_url
        if payload.is_active is not None:
            updates["is_active"] = payload.is_active
        if payload.profile_schema is not None:
            updates["profile_schema"] = [field.model_dump() for field in payload.profile_schema]

        game = await self.game_repo.update(game, **updates)
        await self.session.commit()
        return game

    async def _validate_profile_data(self, game: Game, data: dict) -> None:
        """Validate submitted profile data against the game's dynamic profile_schema."""
        required_keys = {
            field["key"] for field in game.profile_schema if field.get("required", True)
        }
        missing = required_keys - data.keys()
        if missing:
            raise ValidationException(
                f"Missing required fields for {game.name}: {', '.join(sorted(missing))}"
            )

    async def create_game_profile(
        self, user_id: UUID, payload: UserGameProfileCreate
    ) -> UserGameProfile:
        game = await self.game_repo.get_by_id(payload.game_id)
        if game is None or not game.is_active:
            raise NotFoundException("Game not found")

        existing = await self.profile_repo.get_by_user_and_game(user_id, payload.game_id)
        if existing is not None:
            raise ConflictException("A profile for this game already exists. Use update instead.")

        await self._validate_profile_data(game, payload.data)

        profile = await self.profile_repo.create(
            user_id=user_id, game_id=payload.game_id, data=payload.data
        )
        await self.session.commit()
        return profile

    async def update_game_profile(
        self, user_id: UUID, game_id: UUID, payload: UserGameProfileUpdate
    ) -> UserGameProfile:
        game = await self.game_repo.get_by_id(game_id)
        if game is None:
            raise NotFoundException("Game not found")

        profile = await self.profile_repo.get_by_user_and_game(user_id, game_id)
        if profile is None:
            raise NotFoundException("Game profile not found")

        await self._validate_profile_data(game, payload.data)

        profile = await self.profile_repo.update(profile, data=payload.data)
        await self.session.commit()
        return profile

    async def list_user_game_profiles(self, user_id: UUID) -> list[UserGameProfile]:
        return await self.profile_repo.list_for_user(user_id)
