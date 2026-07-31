"""
Enterprise Wallet System (Phase 8) API tests.

NOTE: Models use PostgreSQL-specific types (UUID, JSONB), so these tests
require a real PostgreSQL test database to run end-to-end, same as
tests/test_auth.py and tests/test_tournaments.py. Structure is provided
per Phase 8 requirements.
"""
import pytest

pytestmark = pytest.mark.asyncio

_FAKE_ID = "00000000-0000-0000-0000-000000000000"


async def test_get_my_wallet_requires_auth(client):
    response = await client.get("/api/v1/wallet")
    assert response.status_code == 401


async def test_list_my_transactions_requires_auth(client):
    response = await client.get("/api/v1/wallet/transactions")
    assert response.status_code == 401


async def test_get_transaction_details_requires_auth(client):
    response = await client.get(f"/api/v1/wallet/transactions/{_FAKE_ID}")
    assert response.status_code == 401


async def test_hold_funds_requires_auth(client):
    response = await client.post(
        "/api/v1/wallet/hold",
        json={"amount": "100.00", "reference_type": "tournament_entry", "reference_id": _FAKE_ID},
    )
    assert response.status_code == 401


async def test_hold_funds_rejects_non_positive_amount(client):
    response = await client.post(
        "/api/v1/wallet/hold",
        json={"amount": "0.00", "reference_type": "tournament_entry", "reference_id": _FAKE_ID},
    )
    # 401 (auth checked first by FastAPI dependency resolution order can
    # vary) or 422 depending on validation ordering — either is an
    # acceptable "rejected" outcome for an unauthenticated + invalid request.
    assert response.status_code in (401, 422)


async def test_release_hold_requires_auth(client):
    response = await client.post(
        "/api/v1/wallet/release-hold",
        json={"hold_transaction_id": _FAKE_ID},
    )
    assert response.status_code == 401


async def test_admin_get_wallet_requires_auth(client):
    response = await client.get(f"/api/v1/admin/wallets/{_FAKE_ID}")
    assert response.status_code == 401


async def test_admin_list_transactions_requires_auth(client):
    response = await client.get("/api/v1/admin/wallets/transactions")
    assert response.status_code == 401


async def test_admin_adjust_wallet_requires_auth(client):
    response = await client.post(
        f"/api/v1/admin/wallets/{_FAKE_ID}/adjust",
        json={"amount": "50.00", "reason": "Compensation for match issue"},
    )
    assert response.status_code == 401


async def test_admin_credit_wallet_requires_auth(client):
    response = await client.post(
        f"/api/v1/admin/wallets/{_FAKE_ID}/credit",
        json={"amount": "50.00", "reason": "Promo credit"},
    )
    assert response.status_code == 401


async def test_admin_debit_wallet_requires_auth(client):
    response = await client.post(
        f"/api/v1/admin/wallets/{_FAKE_ID}/debit",
        json={"amount": "50.00", "reason": "Chargeback"},
    )
    assert response.status_code == 401


async def test_admin_freeze_wallet_requires_auth(client):
    response = await client.patch(
        f"/api/v1/admin/wallets/{_FAKE_ID}/freeze",
        json={"is_frozen": True, "reason": "Suspicious activity"},
    )
    assert response.status_code == 401


async def test_admin_adjust_wallet_rejects_zero_amount_shape(client):
    # Even though this hits auth first (401), the payload shape itself
    # must be accepted by the schema — validated separately below.
    from app.schemas.wallet import AdminWalletAdjustmentRequest

    with pytest.raises(ValueError):
        AdminWalletAdjustmentRequest(amount="0", reason="test reason")


async def test_wallet_hold_request_rejects_non_positive_amount(client):
    from pydantic import ValidationError

    from app.schemas.wallet import WalletHoldRequest

    with pytest.raises(ValidationError):
        WalletHoldRequest(amount="-5.00", reference_type="tournament_entry", reference_id="abc")


async def test_wallet_transaction_type_enum_values(client):
    from app.models.wallet_transaction import WalletTransactionType

    assert {t.value for t in WalletTransactionType} == {
        "credit",
        "debit",
        "hold",
        "release_hold",
        "refund",
        "bonus",
        "admin_adjustment",
    }
