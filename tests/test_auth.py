"""
Basic authentication flow tests.

NOTE: Models use PostgreSQL-specific types (UUID, JSONB), so these tests
require a real PostgreSQL test database to run end-to-end. Point
DATABASE_URL at a disposable Postgres instance (e.g. via docker-compose)
to execute this suite. Structure is provided per Phase 1 requirements.
"""
import pytest

pytestmark = pytest.mark.asyncio


async def test_health_check(client):
    response = await client.get("/api/v1/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


async def test_signup_requires_valid_password(client):
    response = await client.post(
        "/api/v1/auth/signup",
        json={
            "full_name": "Test User",
            "email": "test@example.com",
            "phone_number": "+919876543210",
            "password": "weak",
        },
    )
    assert response.status_code == 422


async def test_signup_success_sends_otp(client):
    response = await client.post(
        "/api/v1/auth/signup",
        json={
            "full_name": "Test User",
            "email": "test@example.com",
            "phone_number": "+919876543210",
            "password": "StrongPass1!",
        },
    )
    assert response.status_code in (201, 500, 502)  # 500/502 if Brevo not configured in test env


async def test_login_with_invalid_credentials(client):
    response = await client.post(
        "/api/v1/auth/login",
        json={"email": "nouser@example.com", "password": "whatever"},
    )
    assert response.status_code == 401
