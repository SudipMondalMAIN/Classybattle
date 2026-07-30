"""
AuditService — Phase 7.5 (Backend Hardening).

Single reusable entry point for recording audit events across the whole
application. Any service (Tournament, Team, Match, and — in future —
Wallet/Payment) should call `AuditService.record(...)` instead of writing
directly to the `audit_logs` table, so retention policy, serialization and
request-metadata capture stay consistent everywhere.
"""
from __future__ import annotations

import decimal
import enum
import uuid
from datetime import date, datetime
from typing import Any, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.request_context import get_client_ip, get_request_id
from app.models.audit_log import AuditAction, AuditActorType, AuditLog
from app.models.user import User, UserRole
from app.repositories.audit_log_repository import AuditLogRepository


def _json_safe(value: Any) -> Any:
    """Recursively coerce a value into something JSON/JSONB serializable."""
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, decimal.Decimal):
        return str(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, enum.Enum):
        return value.value
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(v) for v in value]
    return str(value)


def _actor_type_for_role(role: Optional[UserRole]) -> AuditActorType:
    if role in (UserRole.ADMIN, UserRole.SUPER_ADMIN):
        return AuditActorType.ADMIN
    return AuditActorType.USER


class AuditService:
    """Thin wrapper around AuditLogRepository that fills in request
    metadata (request id, IP) automatically from context vars."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repository = AuditLogRepository(session)

    async def record(
        self,
        *,
        entity: str,
        action: AuditAction,
        entity_id: Optional[Any] = None,
        actor: Optional[User] = None,
        actor_type: Optional[AuditActorType] = None,
        old_values: Optional[dict] = None,
        new_values: Optional[dict] = None,
        description: Optional[str] = None,
    ) -> AuditLog:
        """Persist one audit event.

        `actor=None` records a system-initiated action (e.g. a scheduled
        job auto-transitioning a tournament's status) — `actor_type`
        defaults to SYSTEM in that case unless explicitly overridden.
        """
        resolved_actor_type = actor_type
        if resolved_actor_type is None:
            resolved_actor_type = (
                _actor_type_for_role(actor.role) if actor is not None else AuditActorType.SYSTEM
            )

        return await self.repository.create(
            actor_id=actor.id if actor is not None else None,
            actor_type=resolved_actor_type,
            actor_label=(actor.email if actor is not None and hasattr(actor, "email") else None),
            action=action,
            entity=entity,
            entity_id=str(entity_id) if entity_id is not None else None,
            old_values=_json_safe(old_values) if old_values is not None else None,
            new_values=_json_safe(new_values) if new_values is not None else None,
            ip_address=get_client_ip(),
            request_id=get_request_id(),
            description=description,
        )
