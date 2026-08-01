"""
TeamMember model — Team System & Invite Management (Phase 6).
"""
import enum
import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, Enum, ForeignKey, Index, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import BaseModel
from app.database.types import str_enum


class TeamMemberRole(str, enum.Enum):
    CAPTAIN = "captain"
    MEMBER = "member"


class TeamMember(BaseModel):
    __tablename__ = "team_members"
    __table_args__ = (
        UniqueConstraint("team_id", "user_id", name="uq_team_members_team_user"),
        Index("ix_team_members_team_role", "team_id", "role"),
    )

    team_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("teams.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # Links this membership back to the participant record created for the
    # same tournament, keeping capacity/status tracking in one place
    # (Participant remains the source of truth for tournament capacity).
    participant_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("participants.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    role: Mapped[TeamMemberRole] = mapped_column(
        str_enum(TeamMemberRole, "team_member_role"),
        default=TeamMemberRole.MEMBER,
        nullable=False,
    )

    joined_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    team: Mapped["Team"] = relationship(back_populates="members", lazy="selectin")  # noqa: F821
    user: Mapped["User"] = relationship(lazy="selectin")  # noqa: F821
    participant: Mapped[Optional["Participant"]] = relationship(lazy="selectin")  # noqa: F821

    def __repr__(self) -> str:
        return f"<TeamMember id={self.id} team_id={self.team_id} user_id={self.user_id} role={self.role}>"
