"""team community system - phase 15b

Revision ID: 0015_team_community
Revises: 0014_social_system
Create Date: 2026-08-01

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0015_team_community"
down_revision: Union[str, None] = "0014_social_system"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    team_invitation_status = postgresql.ENUM(
        "pending", "accepted", "rejected", "cancelled", "expired", name="team_invitation_status", create_type=False
    )
    team_invitation_status.create(op.get_bind(), checkfirst=True)

    team_join_request_status = postgresql.ENUM(
        "pending", "accepted", "rejected", "cancelled", name="team_join_request_status", create_type=False
    )
    team_join_request_status.create(op.get_bind(), checkfirst=True)

    team_activity_type = postgresql.ENUM(
        "member_joined",
        "member_left",
        "member_removed",
        "captain_transferred",
        "invitation_sent",
        "invitation_accepted",
        "invitation_rejected",
        "invitation_cancelled",
        "join_request_sent",
        "join_request_accepted",
        "join_request_rejected",
        "join_request_cancelled",
        "announcement_posted",
        "announcement_updated",
        "announcement_deleted",
        "team_locked",
        "team_unlocked",
        "team_disbanded",
        name="team_activity_type",
        create_type=False,
    )
    team_activity_type.create(op.get_bind(), checkfirst=True)

    # ------------------------------------------------------------------
    # team_invitations
    # ------------------------------------------------------------------
    op.create_table(
        "team_invitations",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False, unique=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("team_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("teams.id", ondelete="CASCADE"), nullable=False),
        sa.Column("tournament_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tournaments.id", ondelete="CASCADE"), nullable=False),
        sa.Column("inviter_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("invitee_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("status", team_invitation_status, nullable=False, server_default="pending"),
        sa.Column("message", sa.String(length=500), nullable=True),
        sa.Column("responded_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("team_id", "invitee_id", name="uq_team_invitation_team_invitee"),
    )
    op.create_index("ix_team_invitations_team_id", "team_invitations", ["team_id"])
    op.create_index("ix_team_invitations_tournament_id", "team_invitations", ["tournament_id"])
    op.create_index("ix_team_invitations_inviter_id", "team_invitations", ["inviter_id"])
    op.create_index("ix_team_invitations_invitee_id", "team_invitations", ["invitee_id"])
    op.create_index("ix_team_invitations_status", "team_invitations", ["status"])
    op.create_index("ix_team_invitations_team_status", "team_invitations", ["team_id", "status"])
    op.create_index("ix_team_invitations_invitee_status", "team_invitations", ["invitee_id", "status"])

    # ------------------------------------------------------------------
    # team_join_requests
    # ------------------------------------------------------------------
    op.create_table(
        "team_join_requests",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False, unique=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("team_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("teams.id", ondelete="CASCADE"), nullable=False),
        sa.Column("tournament_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tournaments.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("status", team_join_request_status, nullable=False, server_default="pending"),
        sa.Column("message", sa.String(length=500), nullable=True),
        sa.Column("responded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reviewed_by_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.UniqueConstraint("team_id", "user_id", name="uq_team_join_request_team_user"),
    )
    op.create_index("ix_team_join_requests_team_id", "team_join_requests", ["team_id"])
    op.create_index("ix_team_join_requests_tournament_id", "team_join_requests", ["tournament_id"])
    op.create_index("ix_team_join_requests_user_id", "team_join_requests", ["user_id"])
    op.create_index("ix_team_join_requests_status", "team_join_requests", ["status"])
    op.create_index("ix_team_join_requests_team_status", "team_join_requests", ["team_id", "status"])
    op.create_index("ix_team_join_requests_user_status", "team_join_requests", ["user_id", "status"])

    # ------------------------------------------------------------------
    # team_announcements
    # ------------------------------------------------------------------
    op.create_table(
        "team_announcements",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False, unique=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("team_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("teams.id", ondelete="CASCADE"), nullable=False),
        sa.Column("author_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("content", sa.String(length=2000), nullable=False),
        sa.Column("is_pinned", sa.Boolean, nullable=False, server_default=sa.false()),
    )
    op.create_index("ix_team_announcements_team_id", "team_announcements", ["team_id"])
    op.create_index("ix_team_announcements_author_id", "team_announcements", ["author_id"])
    op.create_index("ix_team_announcements_team_created", "team_announcements", ["team_id", "created_at"])
    op.create_index("ix_team_announcements_team_pinned", "team_announcements", ["team_id", "is_pinned"])

    # ------------------------------------------------------------------
    # team_activity_feed_entries
    # ------------------------------------------------------------------
    op.create_table(
        "team_activity_feed_entries",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False, unique=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("team_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("teams.id", ondelete="CASCADE"), nullable=False),
        sa.Column("actor_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("activity_type", team_activity_type, nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("meta_data", postgresql.JSONB, nullable=True),
        sa.Column("event_key", sa.String(length=255), nullable=True),
        sa.UniqueConstraint("event_key", name="uq_team_activity_feed_event_key"),
    )
    op.create_index("ix_team_activity_feed_team_id", "team_activity_feed_entries", ["team_id"])
    op.create_index("ix_team_activity_feed_actor_id", "team_activity_feed_entries", ["actor_id"])
    op.create_index("ix_team_activity_feed_activity_type", "team_activity_feed_entries", ["activity_type"])
    op.create_index("ix_team_activity_feed_event_key", "team_activity_feed_entries", ["event_key"])
    op.create_index("ix_team_activity_feed_team_created", "team_activity_feed_entries", ["team_id", "created_at"])
    op.create_index("ix_team_activity_feed_team_type", "team_activity_feed_entries", ["team_id", "activity_type"])


def downgrade() -> None:
    op.drop_index("ix_team_activity_feed_team_type", table_name="team_activity_feed_entries")
    op.drop_index("ix_team_activity_feed_team_created", table_name="team_activity_feed_entries")
    op.drop_index("ix_team_activity_feed_event_key", table_name="team_activity_feed_entries")
    op.drop_index("ix_team_activity_feed_activity_type", table_name="team_activity_feed_entries")
    op.drop_index("ix_team_activity_feed_actor_id", table_name="team_activity_feed_entries")
    op.drop_index("ix_team_activity_feed_team_id", table_name="team_activity_feed_entries")
    op.drop_table("team_activity_feed_entries")

    op.drop_index("ix_team_announcements_team_pinned", table_name="team_announcements")
    op.drop_index("ix_team_announcements_team_created", table_name="team_announcements")
    op.drop_index("ix_team_announcements_author_id", table_name="team_announcements")
    op.drop_index("ix_team_announcements_team_id", table_name="team_announcements")
    op.drop_table("team_announcements")

    op.drop_index("ix_team_join_requests_user_status", table_name="team_join_requests")
    op.drop_index("ix_team_join_requests_team_status", table_name="team_join_requests")
    op.drop_index("ix_team_join_requests_status", table_name="team_join_requests")
    op.drop_index("ix_team_join_requests_user_id", table_name="team_join_requests")
    op.drop_index("ix_team_join_requests_tournament_id", table_name="team_join_requests")
    op.drop_index("ix_team_join_requests_team_id", table_name="team_join_requests")
    op.drop_table("team_join_requests")

    op.drop_index("ix_team_invitations_invitee_status", table_name="team_invitations")
    op.drop_index("ix_team_invitations_team_status", table_name="team_invitations")
    op.drop_index("ix_team_invitations_status", table_name="team_invitations")
    op.drop_index("ix_team_invitations_invitee_id", table_name="team_invitations")
    op.drop_index("ix_team_invitations_inviter_id", table_name="team_invitations")
    op.drop_index("ix_team_invitations_tournament_id", table_name="team_invitations")
    op.drop_index("ix_team_invitations_team_id", table_name="team_invitations")
    op.drop_table("team_invitations")

    bind = op.get_bind()
    postgresql.ENUM(name="team_activity_type").drop(bind, checkfirst=True)
    postgresql.ENUM(name="team_join_request_status").drop(bind, checkfirst=True)
    postgresql.ENUM(name="team_invitation_status").drop(bind, checkfirst=True)
