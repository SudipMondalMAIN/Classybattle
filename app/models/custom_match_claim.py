"""
CustomMatchClaim model — self-declared win/loss results for 1v1 Custom
Tournaments (Phase 19).

Custom Tournaments (user-hosted, category IS NULL, max_players == 2) have
no admin refereeing the match, so the two players report the outcome
themselves instead of an admin declaring a winner:

- Claiming LOSS never needs proof -- it immediately auto-declares the
  *other* player the winner and pays them out on the spot (a player has
  no incentive to falsely confess a loss, so this is safe to trust).
- Claiming WIN requires a proof screenshot and stays PENDING_REVIEW
  until either (a) the opponent separately claims LOSS, which
  auto-confirms it, or (b) an admin reviews the proof and approves it.
- If both players claim WIN (a genuine dispute), both stay
  PENDING_REVIEW for an admin to resolve manually.

One row per (tournament, user) -- resubmitting (e.g. after a REJECTED
claim) updates the same row rather than creating a new one.
"""
import enum
import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import BaseModel
from app.database.types import str_enum


class CustomMatchClaimOutcome(str, enum.Enum):
    WIN = "win"
    LOSS = "loss"


class CustomMatchClaimStatus(str, enum.Enum):
    # Awaiting either the opponent's confirming claim or admin review.
    PENDING_REVIEW = "pending_review"
    # Resolved automatically because the opponent's claim confirmed it
    # (they claimed LOSS, or this row itself was a LOSS claim that
    # immediately crowns the opponent) -- no admin involved.
    AUTO_RESOLVED = "auto_resolved"
    # An admin reviewed the proof and approved this WIN claim.
    ADMIN_APPROVED = "admin_approved"
    # An admin rejected this claim (bad/missing proof, mismatched
    # scoreline, etc). Can be resubmitted, which flips it back to
    # PENDING_REVIEW.
    REJECTED = "rejected"


class CustomMatchClaim(BaseModel):
    __tablename__ = "custom_match_claims"
    __table_args__ = (
        UniqueConstraint(
            "tournament_id", "user_id", name="uq_custom_match_claims_tournament_user"
        ),
        Index("ix_custom_match_claims_tournament_status", "tournament_id", "status"),
    )

    tournament_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tournaments.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    outcome: Mapped[CustomMatchClaimOutcome] = mapped_column(
        str_enum(CustomMatchClaimOutcome, "custom_match_claim_outcome"), nullable=False
    )
    # Required when outcome == WIN, always null for LOSS claims.
    proof_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)

    status: Mapped[CustomMatchClaimStatus] = mapped_column(
        str_enum(CustomMatchClaimStatus, "custom_match_claim_status"),
        default=CustomMatchClaimStatus.PENDING_REVIEW,
        nullable=False,
        index=True,
    )

    submitted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    resolved_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    resolved_by: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    rejection_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    tournament: Mapped["Tournament"] = relationship(lazy="selectin")  # noqa: F821
    user: Mapped["User"] = relationship(foreign_keys=[user_id], lazy="selectin")  # noqa: F821

    def __repr__(self) -> str:
        return (
            f"<CustomMatchClaim id={self.id} tournament_id={self.tournament_id} "
            f"user_id={self.user_id} outcome={self.outcome} status={self.status}>"
        )
