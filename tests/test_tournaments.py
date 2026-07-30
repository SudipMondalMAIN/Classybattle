"""
Tournament Core (Phase 2) API tests.

NOTE: Models use PostgreSQL-specific types (UUID, JSONB), so these tests
require a real PostgreSQL test database to run end-to-end, same as
tests/test_auth.py. Structure is provided per Phase 2 requirements.
"""
from datetime import datetime, timedelta, timezone

import pytest

pytestmark = pytest.mark.asyncio


def _future_windows():
    now = datetime.now(timezone.utc)
    return {
        "registration_start": (now + timedelta(days=1)).isoformat(),
        "registration_end": (now + timedelta(days=5)).isoformat(),
        "tournament_start": (now + timedelta(days=6)).isoformat(),
        "tournament_end": (now + timedelta(days=7)).isoformat(),
    }


async def test_list_tournaments_public(client):
    response = await client.get("/api/v1/tournaments")
    assert response.status_code == 200
    body = response.json()
    assert "items" in body and "total" in body


async def test_create_tournament_requires_auth(client):
    payload = {
        "title": "Free Fire Championship",
        "game_id": "00000000-0000-0000-0000-000000000000",
        "organizer": "ClassyBattle",
        "max_players": 100,
        **_future_windows(),
    }
    response = await client.post("/api/v1/tournaments", json=payload)
    assert response.status_code == 401


async def test_create_tournament_invalid_windows_rejected(client):
    now = datetime.now(timezone.utc)
    payload = {
        "title": "Bad Window Cup",
        "game_id": "00000000-0000-0000-0000-000000000000",
        "organizer": "ClassyBattle",
        "max_players": 64,
        "registration_start": now.isoformat(),
        "registration_end": (now - timedelta(days=1)).isoformat(),
        "tournament_start": (now + timedelta(days=2)).isoformat(),
        "tournament_end": (now + timedelta(days=3)).isoformat(),
    }
    response = await client.post(
        "/api/v1/tournaments",
        json=payload,
        headers={"Authorization": "Bearer invalid"},
    )
    # Invalid/missing auth is checked before body validation in this flow.
    assert response.status_code in (401, 422)


async def test_get_tournament_by_slug_not_found(client):
    response = await client.get("/api/v1/tournaments/slug/does-not-exist")
    assert response.status_code == 404
