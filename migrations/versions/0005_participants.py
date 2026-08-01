"""tournament registration & participants - phase 5

Revision ID: 0005_participants
Revises: 0004_maps
Create Date: 2026-07-30

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0005_participants"
down_revision: Union[str, None] = "0004_maps"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _base_columns():
    return [
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False, unique=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    ]


def upgrade() -> None:
    registration_type = postgresql.ENUM(
        "solo", "duo", "squad", "team", name="participant_registration_type", create_type=False
    )
    participant_status = postgresql.ENUM(
        "pending", "confirmed", "cancelled", "rejected", "checked_in",
        name="participant_status",
        create_type=False,
    )
    participant_payment_status = postgresql.ENUM(
        "not_required", "pending", "paid", "failed", "refunded",
        name="participant_payment_status",
        create_type=False,
    )

    bind = op.get_bind()
    registration_type.create(bind, checkfirst=True)
    participant_status.create(bind, checkfirst=True)
    participant_payment_status.create(bind, checkfirst=True)

    op.create_table(
        "participants",
        *_base_columns(),
        sa.Column("participant_uid", sa.String(20), nullable=False),
        sa.Column(
            "tournament_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tournaments.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "game_profile_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("user_game_profiles.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("registration_type", registration_type, nullable=False, server_default="solo"),
        sa.Column("team_name", sa.String(150), nullable=True),
        sa.Column("status", participant_status, nullable=False, server_default="pending"),
        sa.Column(
            "payment_status",
            participant_payment_status,
            nullable=False,
            server_default="not_required",
        ),
        sa.Column("payment_reference", sa.String(150), nullable=True),
        sa.Column("entry_fee_paid", sa.Numeric(10, 2), nullable=False, server_default="0"),
        sa.Column("joined_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("checked_in_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("participant_uid", name="uq_participants_participant_uid"),
        sa.UniqueConstraint(
            "tournament_id", "user_id", name="uq_participants_tournament_user"
        ),
        sa.CheckConstraint(
            "entry_fee_paid >= 0", name="ck_participants_entry_fee_non_negative"
        ),
    )

    op.create_index("ix_participants_participant_uid", "participants", ["participant_uid"])
    op.create_index("ix_participants_tournament_id", "participants", ["tournament_id"])
    op.create_index("ix_participants_user_id", "participants", ["user_id"])
    op.create_index("ix_participants_game_profile_id", "participants", ["game_profile_id"])
    op.create_index("ix_participants_status", "participants", ["status"])
    op.create_index(
        "ix_participants_tournament_status", "participants", ["tournament_id", "status"]
    )
    op.create_index(
        "ix_participants_user_status", "participants", ["user_id", "status"]
    )


def downgrade() -> None:
    op.drop_index("ix_participants_user_status", table_name="participants")
    op.drop_index("ix_participants_tournament_status", table_name="participants")
    op.drop_index("ix_participants_status", table_name="participants")
    op.drop_index("ix_participants_game_profile_id", table_name="participants")
    op.drop_index("ix_participants_user_id", table_name="participants")
    op.drop_index("ix_participants_tournament_id", table_name="participants")
    op.drop_index("ix_participants_participant_uid", table_name="participants")
    op.drop_table("participants")

    bind = op.get_bind()
    postgresql.ENUM(name="participant_payment_status").drop(bind, checkfirst=True)
    postgresql.ENUM(name="participant_status").drop(bind, checkfirst=True)
    postgresql.ENUM(name="participant_registration_type").drop(bind, checkfirst=True)
