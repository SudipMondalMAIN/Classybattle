"""
Tournament Registration & Entry Fee System (Phase 9) API tests.

NOTE: Models use PostgreSQL-specific types (UUID, JSONB), so full
end-to-end wallet-debit / refund flows require a real PostgreSQL test
database, same as tests/test_participants.py and tests/test_wallet.py.
These tests cover the auth/route-level contracts for the Phase 9 surface
area (idempotent registration, admin cancel-with-refund path via the
existing status endpoint, and tournament cancellation triggering bulk
refunds), which run against the in-memory SQLite fixture.
"""
import pytest

pytestmark = pytest.mark.asyncio

_FAKE_ID = "00000000-0000-0000-0000-000000000000"


async def test_register_idempotent_replay_requires_auth(client):
    """Two identical requests with the same Idempotency-Key must both be
    rejected the same way (401) when unauthenticated — the idempotency
    guard must not bypass authentication."""
    headers = {"Idempotency-Key": "replay-key-1"}
    payload = {"game_profile_id": _FAKE_ID}

    first = await client.post(
        f"/api/v1/tournaments/{_FAKE_ID}/register", json=payload, headers=headers
    )
    second = await client.post(
        f"/api/v1/tournaments/{_FAKE_ID}/register", json=payload, headers=headers
    )
    assert first.status_code == 401
    assert second.status_code == 401


async def test_admin_cancel_participant_status_requires_auth(client):
    """The admin/organizer cancel-with-refund path reuses the existing
    PATCH /participants/{id}/status endpoint — it must still require
    authentication."""
    response = await client.patch(
        f"/api/v1/participants/{_FAKE_ID}/status",
        json={"status": "cancelled"},
    )
    assert response.status_code == 401


async def test_admin_reject_participant_status_requires_auth(client):
    response = await client.patch(
        f"/api/v1/participants/{_FAKE_ID}/status",
        json={"status": "rejected"},
    )
    assert response.status_code == 401


async def test_tournament_status_update_requires_auth(client):
    """Cancelling a tournament (which triggers bulk participant refunds
    per Phase 9) is gated by the existing tournament status endpoint."""
    response = await client.patch(
        f"/api/v1/tournaments/{_FAKE_ID}/status",
        json={"status": "cancelled"},
    )
    assert response.status_code == 401


async def test_registration_history_requires_auth(client):
    response = await client.get("/api/v1/users/me/registrations")
    assert response.status_code == 401
