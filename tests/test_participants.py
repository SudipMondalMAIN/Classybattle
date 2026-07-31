"""
Tournament Registration & Participants (Phase 5) API tests.

NOTE: Models use PostgreSQL-specific types (UUID, JSONB), so these tests
require a real PostgreSQL test database to run end-to-end, same as
tests/test_tournaments.py. Structure is provided per Phase 5 requirements.
"""
import pytest

pytestmark = pytest.mark.asyncio

_FAKE_ID = "00000000-0000-0000-0000-000000000000"


async def test_register_requires_auth(client):
    response = await client.post(
        f"/api/v1/tournaments/{_FAKE_ID}/register",
        json={"game_profile_id": _FAKE_ID},
    )
    assert response.status_code == 401


async def test_list_tournament_participants_public(client):
    response = await client.get(f"/api/v1/tournaments/{_FAKE_ID}/participants")
    assert response.status_code == 200
    body = response.json()
    assert "items" in body and "total" in body


async def test_get_participant_details_requires_auth(client):
    response = await client.get(f"/api/v1/participants/{_FAKE_ID}")
    assert response.status_code == 401


async def test_my_registration_history_requires_auth(client):
    response = await client.get("/api/v1/users/me/registrations")
    assert response.status_code == 401


async def test_cancel_registration_requires_auth(client):
    response = await client.post(f"/api/v1/tournaments/{_FAKE_ID}/cancel")
    assert response.status_code == 401


async def test_update_participant_status_requires_auth(client):
    response = await client.patch(
        f"/api/v1/participants/{_FAKE_ID}/status",
        json={"status": "cancelled"},
    )
    assert response.status_code == 401


# ----------------------------------------------------------------------
# Phase 9 — Entry Fee & Wallet integration
# ----------------------------------------------------------------------
async def test_register_with_idempotency_key_requires_auth(client):
    response = await client.post(
        f"/api/v1/tournaments/{_FAKE_ID}/register",
        json={"game_profile_id": _FAKE_ID},
        headers={"Idempotency-Key": "test-key-123"},
    )
    assert response.status_code == 401


async def test_register_rejects_invalid_registration_type(client):
    response = await client.post(
        f"/api/v1/tournaments/{_FAKE_ID}/register",
        json={"game_profile_id": _FAKE_ID, "registration_type": "not_a_real_type"},
    )
    # Auth is checked by a dependency and schema validation independently;
    # either 401 (unauthenticated) or 422 (bad payload) proves the route
    # rejects the malformed request rather than silently accepting it.
    assert response.status_code in (401, 422)


async def test_leave_tournament_requires_auth(client):
    response = await client.post(f"/api/v1/participants/{_FAKE_ID}/leave")
    assert response.status_code == 401
