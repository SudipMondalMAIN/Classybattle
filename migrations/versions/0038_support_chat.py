"""support chat sessions & messages

Revision ID: 0038_support_chat
Revises: 0037_withdrawal_settings
Create Date: 2026-08-21

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0038_support_chat"
down_revision: Union[str, None] = "0037_withdrawal_settings"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

support_chat_status = postgresql.ENUM(
    "waiting", "active", "closed", name="support_chat_status", create_type=False
)
support_chat_closed_by = postgresql.ENUM("user", "agent", name="support_chat_closed_by", create_type=False)
support_chat_sender_type = postgresql.ENUM(
    "user", "agent", "system", name="support_chat_sender_type", create_type=False
)


def upgrade() -> None:
    bind = op.get_bind()
    support_chat_status.create(bind, checkfirst=True)
    support_chat_closed_by.create(bind, checkfirst=True)
    support_chat_sender_type.create(bind, checkfirst=True)

    op.create_table(
        "support_chat_sessions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, unique=True, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            onupdate=sa.func.now(),
            nullable=False,
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("agent_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("status", support_chat_status, nullable=False, server_default="waiting"),
        sa.Column("closed_by", support_chat_closed_by, nullable=True),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_message_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_support_chat_sessions_user_id", "support_chat_sessions", ["user_id"])
    op.create_index("ix_support_chat_sessions_agent_id", "support_chat_sessions", ["agent_id"])
    op.create_index("ix_support_chat_sessions_status", "support_chat_sessions", ["status"])
    # Fast lookup of "does this user already have an open session".
    op.create_index(
        "ix_support_chat_sessions_user_open",
        "support_chat_sessions",
        ["user_id", "status"],
    )

    op.create_table(
        "support_chat_messages",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, unique=True, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            onupdate=sa.func.now(),
            nullable=False,
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "session_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("support_chat_sessions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("sender_type", support_chat_sender_type, nullable=False),
        sa.Column("sender_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("content", sa.Text(), nullable=False),
    )
    op.create_index("ix_support_chat_messages_session_id", "support_chat_messages", ["session_id"])


def downgrade() -> None:
    op.drop_index("ix_support_chat_messages_session_id", table_name="support_chat_messages")
    op.drop_table("support_chat_messages")

    op.drop_index("ix_support_chat_sessions_user_open", table_name="support_chat_sessions")
    op.drop_index("ix_support_chat_sessions_status", table_name="support_chat_sessions")
    op.drop_index("ix_support_chat_sessions_agent_id", table_name="support_chat_sessions")
    op.drop_index("ix_support_chat_sessions_user_id", table_name="support_chat_sessions")
    op.drop_table("support_chat_sessions")

    bind = op.get_bind()
    support_chat_sender_type.drop(bind, checkfirst=True)
    support_chat_closed_by.drop(bind, checkfirst=True)
    support_chat_status.drop(bind, checkfirst=True)
