"""
Seed script — inserts a starter set of games with their dynamic profile
schemas. Run with: python -m scripts.seed_games
"""
import asyncio

from app.database.session import AsyncSessionLocal
from app.repositories.game_repository import GameRepository

GAMES = [
    {
        "name": "Free Fire",
        "slug": "free-fire",
        "profile_schema": [
            {"key": "nickname", "label": "Nickname", "type": "string", "required": True},
            {"key": "uid", "label": "UID", "type": "string", "required": True},
        ],
    },
    {
        "name": "BGMI",
        "slug": "bgmi",
        "profile_schema": [
            {"key": "nickname", "label": "Nickname", "type": "string", "required": True},
            {"key": "uid", "label": "UID", "type": "string", "required": True},
        ],
    },
    {
        "name": "COD Mobile",
        "slug": "cod-mobile",
        "profile_schema": [
            {"key": "nickname", "label": "Nickname", "type": "string", "required": True},
            {"key": "uid", "label": "UID", "type": "string", "required": True},
        ],
    },
    {
        "name": "Valorant",
        "slug": "valorant",
        "profile_schema": [
            {"key": "riot_id", "label": "Riot ID", "type": "string", "required": True},
        ],
    },
]


async def seed_games() -> None:
    async with AsyncSessionLocal() as session:
        repo = GameRepository(session)
        for game_data in GAMES:
            existing = await repo.get_by_slug(game_data["slug"])
            if existing is None:
                await repo.create(**game_data, icon_url=None, is_active=True)
                print(f"Created game: {game_data['name']}")
            elif not existing.profile_schema:
                # Game row already exists but was created before profile_schema
                # was populated (or created with an empty one) -- backfill it so
                # the app can render the nickname/UID fields.
                await repo.update(existing, profile_schema=game_data["profile_schema"])
                print(f"Backfilled profile_schema for: {game_data['name']}")
            else:
                print(f"Game already exists (schema OK): {game_data['name']}")
        await session.commit()


if __name__ == "__main__":
    asyncio.run(seed_games())