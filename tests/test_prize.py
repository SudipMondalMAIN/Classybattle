"""
Prize Pool & Prize Distribution System (Phase 10) API tests.

NOTE: Models use PostgreSQL-specific types (UUID, JSONB), so these tests
require a real PostgreSQL test database to run end-to-end, same as
tests/test_wallet.py and tests/test_tournaments.py. Structure is provided
per Phase 10 requirements; auth/validation logic is exercised directly
where it doesn't require the database.
"""
from decimal import Decimal

import pytest

pytestmark = pytest.mark.asyncio

_FAKE_ID = "00000000-0000-0000-0000-000000000000"


# ----------------------------------------------------------------------
# Auth guards
# ----------------------------------------------------------------------
async def test_create_prize_pool_requires_admin(client):
    response = await client.post(
        f"/api/v1/admin/tournaments/{_FAKE_ID}/prize-pool",
        json={
            "total_amount": "1000.00",
            "distribution_type": "single_winner",
            "distribution_rules": [{"rank": 1, "percentage": "100.00"}],
        },
    )
    assert response.status_code == 401


async def test_update_prize_pool_requires_admin(client):
    response = await client.patch(
        f"/api/v1/admin/tournaments/{_FAKE_ID}/prize-pool",
        json={"total_amount": "2000.00"},
    )
    assert response.status_code == 401


async def test_publish_prize_pool_requires_admin(client):
    response = await client.post(f"/api/v1/admin/tournaments/{_FAKE_ID}/prize-pool/publish")
    assert response.status_code == 401


async def test_cancel_prize_pool_requires_admin(client):
    response = await client.post(
        f"/api/v1/admin/tournaments/{_FAKE_ID}/prize-pool/cancel",
        params={"reason": "Tournament cancelled"},
    )
    assert response.status_code == 401


async def test_admin_list_prize_pools_requires_admin(client):
    response = await client.get("/api/v1/admin/prize-pools")
    assert response.status_code == 401


async def test_assign_winners_requires_admin(client):
    response = await client.post(
        f"/api/v1/admin/tournaments/{_FAKE_ID}/prize-pool/winners",
        json={"winners": [{"rank": 1, "participant_id": _FAKE_ID}]},
    )
    assert response.status_code == 401


async def test_distribute_prizes_requires_admin(client):
    response = await client.post(f"/api/v1/admin/tournaments/{_FAKE_ID}/prize-pool/distribute")
    assert response.status_code == 401


async def test_admin_manual_payout_requires_admin(client):
    response = await client.post(
        f"/api/v1/admin/prize-payouts/{_FAKE_ID}/pay",
        json={"reason": "Manual settlement after gateway outage"},
    )
    assert response.status_code == 401


async def test_retry_prize_payout_requires_admin(client):
    response = await client.post(f"/api/v1/admin/prize-payouts/{_FAKE_ID}/retry")
    assert response.status_code == 401


async def test_admin_list_prize_payouts_requires_admin(client):
    response = await client.get("/api/v1/admin/prize-payouts")
    assert response.status_code == 401


async def test_list_my_prize_payouts_requires_auth(client):
    response = await client.get("/api/v1/prize-payouts/me")
    assert response.status_code == 401


async def test_get_prize_payout_requires_auth(client):
    response = await client.get(f"/api/v1/prize-payouts/{_FAKE_ID}")
    assert response.status_code == 401


async def test_get_tournament_prize_pool_not_found(client):
    # Public endpoint — no auth required, but the pool doesn't exist yet.
    response = await client.get(f"/api/v1/tournaments/{_FAKE_ID}/prize-pool")
    assert response.status_code == 404


async def test_list_tournament_prize_payouts_public(client):
    response = await client.get(f"/api/v1/tournaments/{_FAKE_ID}/prize-payouts")
    assert response.status_code == 200
    body = response.json()
    assert body["items"] == []
    assert body["total"] == 0


# ----------------------------------------------------------------------
# Schema validation
# ----------------------------------------------------------------------
def test_prize_pool_create_single_winner_valid():
    from app.schemas.prize import PrizePoolCreate

    pool = PrizePoolCreate(
        total_amount=Decimal("1000.00"),
        distribution_type="single_winner",
        distribution_rules=[{"rank": 1, "percentage": "100.00"}],
    )
    assert pool.distribution_rules[0].percentage == Decimal("100.00")


def test_prize_pool_create_top_n_percentages_must_sum_to_100():
    from pydantic import ValidationError

    from app.schemas.prize import PrizePoolCreate

    with pytest.raises(ValidationError):
        PrizePoolCreate(
            total_amount=Decimal("1000.00"),
            distribution_type="top_n",
            distribution_rules=[
                {"rank": 1, "percentage": "60.00"},
                {"rank": 2, "percentage": "30.00"},
            ],
        )


def test_prize_pool_create_fixed_amount_must_sum_to_total():
    from pydantic import ValidationError

    from app.schemas.prize import PrizePoolCreate

    with pytest.raises(ValidationError):
        PrizePoolCreate(
            total_amount=Decimal("1000.00"),
            distribution_type="fixed_amount",
            distribution_rules=[
                {"rank": 1, "amount": "500.00"},
                {"rank": 2, "amount": "400.00"},
            ],
        )


def test_prize_pool_create_fixed_amount_valid():
    from app.schemas.prize import PrizePoolCreate

    pool = PrizePoolCreate(
        total_amount=Decimal("1000.00"),
        distribution_type="fixed_amount",
        distribution_rules=[
            {"rank": 1, "amount": "600.00"},
            {"rank": 2, "amount": "400.00"},
        ],
    )
    assert pool.distribution_rules[1].amount == Decimal("400.00")


def test_prize_pool_create_rejects_non_contiguous_ranks():
    from pydantic import ValidationError

    from app.schemas.prize import PrizePoolCreate

    with pytest.raises(ValidationError):
        PrizePoolCreate(
            total_amount=Decimal("1000.00"),
            distribution_type="top_n",
            distribution_rules=[
                {"rank": 1, "percentage": "60.00"},
                {"rank": 3, "percentage": "40.00"},
            ],
        )


def test_prize_pool_create_rejects_duplicate_ranks():
    from pydantic import ValidationError

    from app.schemas.prize import PrizePoolCreate

    with pytest.raises(ValidationError):
        PrizePoolCreate(
            total_amount=Decimal("1000.00"),
            distribution_type="top_n",
            distribution_rules=[
                {"rank": 1, "percentage": "60.00"},
                {"rank": 1, "percentage": "40.00"},
            ],
        )


def test_prize_rank_rule_requires_exactly_one_of_percentage_or_amount():
    from pydantic import ValidationError

    from app.schemas.prize import PrizeRankRule

    with pytest.raises(ValidationError):
        PrizeRankRule(rank=1, percentage=Decimal("50.00"), amount=Decimal("50.00"))

    with pytest.raises(ValidationError):
        PrizeRankRule(rank=1)


def test_assign_winners_rejects_duplicate_ranks_or_participants():
    from pydantic import ValidationError

    from app.schemas.prize import AssignWinnersRequest

    with pytest.raises(ValidationError):
        AssignWinnersRequest(
            winners=[
                {"rank": 1, "participant_id": _FAKE_ID},
                {"rank": 1, "participant_id": "11111111-1111-1111-1111-111111111111"},
            ]
        )


# ----------------------------------------------------------------------
# Model enum sanity checks
# ----------------------------------------------------------------------
def test_prize_distribution_type_enum_values():
    from app.models.prize import PrizeDistributionType

    assert {t.value for t in PrizeDistributionType} == {
        "single_winner",
        "top_n",
        "percentage",
        "fixed_amount",
    }


def test_prize_pool_status_enum_values():
    from app.models.prize import PrizePoolStatus

    assert {s.value for s in PrizePoolStatus} == {
        "draft",
        "published",
        "distributing",
        "distributed",
        "cancelled",
    }


def test_prize_payout_status_enum_values():
    from app.models.prize import PrizePayoutStatus

    assert {s.value for s in PrizePayoutStatus} == {
        "pending",
        "processing",
        "paid",
        "failed",
        "cancelled",
    }


def test_prize_pool_status_transitions_are_well_formed():
    from app.models.prize import PRIZE_POOL_STATUS_TRANSITIONS, PrizePoolStatus

    assert PrizePoolStatus.PUBLISHED in PRIZE_POOL_STATUS_TRANSITIONS[PrizePoolStatus.DRAFT]
    assert PRIZE_POOL_STATUS_TRANSITIONS[PrizePoolStatus.DISTRIBUTED] == set()
    assert PRIZE_POOL_STATUS_TRANSITIONS[PrizePoolStatus.CANCELLED] == set()
