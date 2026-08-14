"""
Custom Match Claim schemas -- self-declared win/loss for 1v1 Custom
Tournaments.
"""
from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, model_validator

from app.models.custom_match_claim import CustomMatchClaimOutcome


class SubmitClaimRequest(BaseModel):
    outcome: CustomMatchClaimOutcome
    # Required when outcome == "win"; ignored (should be omitted) for
    # "loss" -- a loss never needs proof.
    proof_url: Optional[str] = None

    @model_validator(mode="after")
    def _require_proof_for_win(self) -> "SubmitClaimRequest":
        if self.outcome == CustomMatchClaimOutcome.WIN and not self.proof_url:
            raise ValueError("proof_url is required when claiming a win")
        return self


class RejectClaimRequest(BaseModel):
    reason: str


class CustomMatchClaimRead(BaseModel):
    id: UUID
    tournament_id: UUID
    user_id: UUID
    outcome: str
    proof_url: Optional[str] = None
    status: str
    submitted_at: datetime
    resolved_at: Optional[datetime] = None
    rejection_reason: Optional[str] = None

    class Config:
        from_attributes = True


class CustomMatchClaimPairRead(BaseModel):
    """Both players' claim state for a tournament, so the UI can show
    "waiting for opponent" / "confirmed" / etc without a second call."""

    my_claim: Optional[CustomMatchClaimRead] = None
    opponent_claim: Optional[CustomMatchClaimRead] = None
    # True once either side has been paid out (win credited).
    resolved: bool = False


class PendingClaimAdminRead(CustomMatchClaimRead):
    """Same as CustomMatchClaimRead plus the context an admin needs to
    review it without a second lookup."""

    tournament_title: str
    claimant_name: str
    opponent_user_id: Optional[UUID] = None
    opponent_name: Optional[str] = None
    opponent_outcome: Optional[str] = None
