"""backend hardening - phase 7.5

Revision ID: 0008_backend_hardening
Revises: 0007_matches
Create Date: 2026-07-30

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0008_backend_hardening"
down_revision: Union[str, None] = "0007_matches"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ------------------------------------------------------------------
    # Audit logging system
    # ------------------------------------------------------------------
    audit_actor_type = postgresql.ENUM(
        "user", "admin", "organizer", "system", name="audit_actor_type"
    )
    audit_action = postgresql.ENUM(
        "create",
        "update",
        "delete",
        "status_change",
        "login",
        "logout",
        "permission_change",
        "other",
        name="audit_action",
    )
    bind = op.get_bind()
    audit_actor_type.create(bind, checkfirst=True)
    audit_action.create(bind, checkfirst=True)

    op.create_table(
        "audit_logs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("actor_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "actor_type",
            postgresql.ENUM(
                "user", "admin", "organizer", "system", name="audit_actor_type", create_type=False
            ),
            nullable=False,
        ),
        sa.Column("actor_label", sa.String(length=255), nullable=True),
        sa.Column(
            "action",
            postgresql.ENUM(
                "create",
                "update",
                "delete",
                "status_change",
                "login",
                "logout",
                "permission_change",
                "other",
                name="audit_action",
                create_type=False,
            ),
            nullable=False,
        ),
        sa.Column("entity", sa.String(length=100), nullable=False),
        sa.Column("entity_id", sa.String(length=100), nullable=True),
        sa.Column("old_values", postgresql.JSONB, nullable=True),
        sa.Column("new_values", postgresql.JSONB, nullable=True),
        sa.Column("ip_address", sa.String(length=64), nullable=True),
        sa.Column("request_id", sa.String(length=64), nullable=True),
        sa.Column("description", sa.String(length=500), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["actor_id"], ["users.id"], ondelete="SET NULL"),
    )
    op.create_index("ix_audit_logs_actor_id", "audit_logs", ["actor_id"])
    op.create_index("ix_audit_logs_entity_type_id", "audit_logs", ["entity", "entity_id"])
    op.create_index("ix_audit_logs_actor", "audit_logs", ["actor_id", "actor_type"])
    op.create_index("ix_audit_logs_created_at", "audit_logs", ["created_at"])
    op.create_index("ix_audit_logs_request_id", "audit_logs", ["request_id"])
    op.create_index("ix_audit_logs_action", "audit_logs", ["action"])
    op.create_index("ix_audit_logs_entity", "audit_logs", ["entity"])

    # ------------------------------------------------------------------
    # Idempotency framework
    # ------------------------------------------------------------------
    idempotency_status = postgresql.ENUM(
        "in_progress", "completed", "failed", name="idempotency_key_status"
    )
    idempotency_status.create(bind, checkfirst=True)

    op.create_table(
        "idempotency_keys",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("scope", sa.String(length=100), nullable=False),
        sa.Column("key", sa.String(length=255), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("request_fingerprint", sa.String(length=64), nullable=True),
        sa.Column(
            "status",
            postgresql.ENUM(
                "in_progress",
                "completed",
                "failed",
                name="idempotency_key_status",
                create_type=False,
            ),
            nullable=False,
            server_default="in_progress",
        ),
        sa.Column("response_status_code", sa.Integer(), nullable=True),
        sa.Column("response_body", postgresql.JSONB, nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "locked_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("scope", "key", name="uq_idempotency_scope_key"),
    )
    op.create_index("ix_idempotency_keys_user", "idempotency_keys", ["user_id"])
    op.create_index("ix_idempotency_keys_created_at", "idempotency_keys", ["created_at"])
    op.create_index("ix_idempotency_keys_scope", "idempotency_keys", ["scope"])

    # ------------------------------------------------------------------
    # Tournament mode_id / map_id: free-form String(50) -> FK (UUID)
    # ------------------------------------------------------------------
    # Existing values (if any) are free-form slugs/identifiers, not UUIDs,
    # so they cannot be losslessly cast. We add new UUID columns, drop the
    # old string columns, and rename — any tournament that had a legacy
    # mode_id/map_id value will simply have it cleared and must be
    # re-assigned via the API against the real GameMode/Map tables.
    op.add_column("tournaments", sa.Column("mode_id_new", postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column("tournaments", sa.Column("map_id_new", postgresql.UUID(as_uuid=True), nullable=True))

    op.drop_column("tournaments", "mode_id")
    op.drop_column("tournaments", "map_id")

    op.alter_column("tournaments", "mode_id_new", new_column_name="mode_id")
    op.alter_column("tournaments", "map_id_new", new_column_name="map_id")

    op.create_index("ix_tournaments_mode_id", "tournaments", ["mode_id"])
    op.create_index("ix_tournaments_map_id", "tournaments", ["map_id"])
    op.create_foreign_key(
        "fk_tournaments_mode_id_game_modes",
        "tournaments",
        "game_modes",
        ["mode_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_tournaments_map_id_maps",
        "tournaments",
        "maps",
        ["map_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("fk_tournaments_map_id_maps", "tournaments", type_="foreignkey")
    op.drop_constraint("fk_tournaments_mode_id_game_modes", "tournaments", type_="foreignkey")
    op.drop_index("ix_tournaments_map_id", table_name="tournaments")
    op.drop_index("ix_tournaments_mode_id", table_name="tournaments")

    op.alter_column("tournaments", "mode_id", new_column_name="mode_id_old")
    op.alter_column("tournaments", "map_id", new_column_name="map_id_old")

    op.add_column("tournaments", sa.Column("mode_id", sa.String(length=50), nullable=True))
    op.add_column("tournaments", sa.Column("map_id", sa.String(length=50), nullable=True))

    op.drop_column("tournaments", "mode_id_old")
    op.drop_column("tournaments", "map_id_old")

    op.drop_table("idempotency_keys")
    bind = op.get_bind()
    postgresql.ENUM(name="idempotency_key_status").drop(bind, checkfirst=True)

    op.drop_index("ix_audit_logs_entity", table_name="audit_logs")
    op.drop_index("ix_audit_logs_action", table_name="audit_logs")
    op.drop_index("ix_audit_logs_request_id", table_name="audit_logs")
    op.drop_index("ix_audit_logs_created_at", table_name="audit_logs")
    op.drop_index("ix_audit_logs_actor", table_name="audit_logs")
    op.drop_index("ix_audit_logs_entity_type_id", table_name="audit_logs")
    op.drop_index("ix_audit_logs_actor_id", table_name="audit_logs")
    op.drop_table("audit_logs")
    postgresql.ENUM(name="audit_action").drop(bind, checkfirst=True)
    postgresql.ENUM(name="audit_actor_type").drop(bind, checkfirst=True)
