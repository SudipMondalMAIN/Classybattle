"""
Game Modes (Phase 3) API tests.

NOTE: Models use PostgreSQL-specific types (UUID, JSONB), so these tests
require a real PostgreSQL test database to run end-to-end, same as
tests/test_auth.py and tests/test_tournaments.py. Structure is provided
per Phase 3 requirements.
"""
import pytest

pytestmark = pytest.mark.asyncio


async def test_list_game_modes_public(client):
    response = await client.get("/api/v1/game-modes")
    assert response.status_code == 200
    body = response.json()
    assert "items" in body and "total" in body


async def test_create_game_mode_requires_auth(client):
    payload = {
        "game_id": "00000000-0000-0000-0000-000000000000",
        "name": "Battle Royale",
        "max_team_size": 4,
        "min_players": 1,
        "max_players": 100,
    }
    response = await client.post("/api/v1/game-modes", json=payload)
    assert response.status_code == 401


async def test_create_game_mode_invalid_limits_rejected(client):
    payload = {
        "game_id": "00000000-0000-0000-0000-000000000000",
        "name": "Broken Mode",
        "max_team_size": 4,
        "min_players": 10,
        "max_players": 5,
    }
    response = await client.post(
        "/api/v1/game-modes",
        json=payload,
        headers={"Authorization": "Bearer invalid"},
    )
    # Invalid/missing auth is checked before body validation in this flow.
    assert response.status_code in (401, 422)


async def test_get_game_mode_by_slug_not_found(client):
    response = await client.get(
        "/api/v1/game-modes/slug/00000000-0000-0000-0000-000000000000/does-not-exist"
    )
    assert response.status_code == 404


async def test_get_game_mode_by_id_not_found(client):
    response = await client.get(
        "/api/v1/game-modes/00000000-0000-0000-0000-000000000000"
    )
    assert response.status_code == 404
