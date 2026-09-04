"""support chat image/video messages

Revision ID: 0051_support_chat_media
Revises: 0050_free_schedule_category
Create Date: 2026-09-04

Adds message_type ("text" | "image" | "video") plus media_url /
media_public_id to support_chat_messages so an in-chat attachment (sent
via Cloudinary, see app/storage/cloudinary_service.py) can be rendered
in the transcript alongside plain text messages. content stays required
but now defaults to "" for pure-media messages with no caption.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0051_support_chat_media"
down_revision: Union[str, None] = "0050_free_schedule_category"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

support_chat_message_type = postgresql.ENUM(
    "text", "image", "video", name="support_chat_message_type", create_type=False
)


def upgrade() -> None:
    bind = op.get_bind()
    support_chat_message_type.create(bind, checkfirst=True)

    op.add_column(
        "support_chat_messages",
        sa.Column(
            "message_type",
            support_chat_message_type,
            nullable=False,
            server_default="text",
        ),
    )
    op.add_column("support_chat_messages", sa.Column("media_url", sa.String(length=1024), nullable=True))
    op.add_column("support_chat_messages", sa.Column("media_public_id", sa.String(length=512), nullable=True))

    # content was NOT NULL with no default; existing rows already have a
    # value so this is safe, it just allows future media-only inserts.
    op.alter_column("support_chat_messages", "content", server_default="")


def downgrade() -> None:
    op.alter_column("support_chat_messages", "content", server_default=None)
    op.drop_column("support_chat_messages", "media_public_id")
    op.drop_column("support_chat_messages", "media_url")
    op.drop_column("support_chat_messages", "message_type")

    bind = op.get_bind()
    support_chat_message_type.drop(bind, checkfirst=True)
