"""
Prize Pool & Prize Distribution Pydantic schemas — Phase 10.
"""
from datetime import datetime
from decimal import Decimal
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.models.prize import PrizeDistributionType, PrizePayoutStatus, PrizePoolStatus


# ----------------------------------------------------------------------
# Distribution rule entries
# ----------------------------------------------------------------------
class PrizeRankRule(BaseModel):
    """One rank's share of the prize pool. Exactly one of `percentage` /
    `amount` must be set, matching the parent pool's distribution_type."""

    rank: int = Field(..., gt=0)
    percentage: Optional[Decimal] = Field(None, gt=0, le=100, decimal_places=2)
    amount: Optional[Decimal] = Field(None, gt=0, decimal_places=2)

    @model_validator(mode="after")
    def _exactly_one_value(self) -> "PrizeRankRule":
        if (self.percentage is None) == (self.amount is None):
            raise ValueError(
                f"Rank {self.rank}: exactly one of 'percentage' or 'amount' must be provided"
            )
        return self


# ----------------------------------------------------------------------
# Prize Pool
# ----------------------------------------------------------------------
class PrizePoolCreate(BaseModel):
    total_amount: Decimal = Field(..., gt=0, decimal_places=2)
    distribution_type: PrizeDistributionType
    distribution_rules: list[PrizeRankRule] = Field(..., min_length=1)

    @field_validator("distribution_rules")
    @classmethod
    def _unique_ranks(cls, rules: list[PrizeRankRule]) -> list[PrizeRankRule]:
        ranks = [r.rank for r in rules]
        if len(ranks) != len(set(ranks)):
            raise ValueError("distribution_rules contains duplicate ranks")
        if sorted(ranks) != list(range(1, len(ranks) + 1)):
            raise ValueError("distribution_rules ranks must be contiguous starting at 1")
        return rules

    @model_validator(mode="after")
    def _validate_by_type(self) -> "PrizePoolCreate":
        rules = self.distribution_rules
        if self.distribution_type == PrizeDistributionType.SINGLE_WINNER:
            if len(rules) != 1:
                raise ValueError("single_winner distribution must have exactly one rank")
        if self.distribution_type in (
            PrizeDistributionType.TOP_N,
            PrizeDistributionType.PERCENTAGE,
            PrizeDistributionType.SINGLE_WINNER,
        ):
            if any(r.percentage is None for r in rules):
                raise ValueError(
                    f"distribution_type={self.distribution_type.value} requires 'percentage' on every rule"
                )
            total_pct = sum((r.percentage for r in rules), Decimal("0"))
            if total_pct != Decimal("100.00") and total_pct != Decimal("100"):
                raise ValueError(
                    f"distribution_rules percentages must sum to 100, got {total_pct}"
                )
        if self.distribution_type == PrizeDistributionType.FIXED_AMOUNT:
            if any(r.amount is None for r in rules):
                raise ValueError("distribution_type=fixed_amount requires 'amount' on every rule")
            total_amt = sum((r.amount for r in rules), Decimal("0"))
            if total_amt != self.total_amount:
                raise ValueError(
                    f"Sum of fixed amounts ({total_amt}) must equal total_amount ({self.total_amount})"
                )
        return self


class PrizePoolUpdate(BaseModel):
    total_amount: Optional[Decimal] = Field(None, gt=0, decimal_places=2)
    distribution_type: Optional[PrizeDistributionType] = None
    distribution_rules: Optional[list[PrizeRankRule]] = Field(None, min_length=1)


class PrizePoolRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tournament_id: UUID
    total_amount: Decimal
    currency: str
    distribution_type: PrizeDistributionType
    distribution_rules: list[dict]
    status: PrizePoolStatus
    published_at: Optional[datetime] = None
    distributed_at: Optional[datetime] = None
    created_by: Optional[UUID] = None
    created_at: datetime
    updated_at: datetime


class PaginatedPrizePools(BaseModel):
    items: list[PrizePoolRead]
    total: int
    page: int
    page_size: int
    total_pages: int


# ----------------------------------------------------------------------
# Winner assignment
# ----------------------------------------------------------------------
class WinnerAssignment(BaseModel):
    rank: int = Field(..., gt=0)
    participant_id: UUID


class AssignWinnersRequest(BaseModel):
    winners: list[WinnerAssignment] = Field(..., min_length=1)

    @field_validator("winners")
    @classmethod
    def _unique_ranks_and_participants(cls, winners: list[WinnerAssignment]) -> list[WinnerAssignment]:
        ranks = [w.rank for w in winners]
        participants = [w.participant_id for w in winners]
        if len(ranks) != len(set(ranks)):
            raise ValueError("Duplicate rank in winners list")
        if len(participants) != len(set(participants)):
            raise ValueError("Duplicate participant in winners list")
        return winners


# ----------------------------------------------------------------------
# Prize Payout
# ----------------------------------------------------------------------
class PrizePayoutRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    prize_pool_id: UUID
    tournament_id: UUID
    participant_id: UUID
    user_id: UUID
    rank: int
    amount: Decimal
    currency: str
    status: PrizePayoutStatus
    wallet_transaction_id: Optional[UUID] = None
    failure_reason: Optional[str] = None
    retry_count: int
    paid_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime


class PaginatedPrizePayouts(BaseModel):
    items: list[PrizePayoutRead]
    total: int
    page: int
    page_size: int
    total_pages: int


class AdminManualPayoutRequest(BaseModel):
    reason: str = Field(..., min_length=3, max_length=500)
