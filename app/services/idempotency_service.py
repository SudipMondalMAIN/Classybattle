"""
IdempotencyService — Phase 7.5 (Backend Hardening).

Reusable replay-protection framework for future payment/wallet APIs.
No payment business logic lives here; this only guarantees that a request
carrying the same `Idempotency-Key` (within the same scope) is processed
at most once, and that a retried request receives the original response
instead of re-running side effects.

Usage (future payment endpoint):

    async with idempotency_service.begin(
        scope="wallet.topup", key=idem_key, user_id=user.id, payload=body
    ) as guard:
        if guard.replayed:
            return JSONResponse(guard.response_body, status_code=guard.response_status_code)
        result = await do_the_actual_charge(...)
        await guard.complete(status_code=200, body=result)
"""
from __future__ import annotations

import hashlib
import json
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, AsyncIterator, Optional
from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictException
from app.models.idempotency_key import IdempotencyKey, IdempotencyKeyStatus
from app.repositories.idempotency_repository import IdempotencyKeyRepository

DEFAULT_TTL = timedelta(hours=24)


def _fingerprint(payload: Any) -> str:
    normalized = json.dumps(payload, sort_keys=True, default=str) if payload is not None else ""
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


@dataclass
class IdempotencyGuard:
    record: IdempotencyKey
    replayed: bool
    _repository: IdempotencyKeyRepository

    @property
    def response_status_code(self) -> Optional[int]:
        return self.record.response_status_code

    @property
    def response_body(self) -> Optional[dict]:
        return self.record.response_body

    async def complete(self, *, status_code: int, body: Optional[dict]) -> None:
        await self._repository.mark_completed(self.record, status_code=status_code, body=body)

    async def fail(self) -> None:
        await self._repository.mark_failed(self.record)


class IdempotencyService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repository = IdempotencyKeyRepository(session)

    @asynccontextmanager
    async def begin(
        self,
        *,
        scope: str,
        key: str,
        user_id: Optional[UUID] = None,
        payload: Any = None,
        ttl: timedelta = DEFAULT_TTL,
    ) -> AsyncIterator[IdempotencyGuard]:
        """Acquire (or replay) an idempotency lock for `scope`+`key`.

        Raises ConflictException if the same key is reused with a
        different request payload, or if a request with the same key is
        already in progress concurrently.
        """
        fingerprint = _fingerprint(payload)
        existing = await self.repository.get(scope, key, user_id=user_id)

        if existing is not None:
            if existing.request_fingerprint != fingerprint:
                raise ConflictException(
                    "Idempotency-Key was already used with a different request payload"
                )
            if existing.status == IdempotencyKeyStatus.IN_PROGRESS:
                raise ConflictException(
                    "A request with this Idempotency-Key is already being processed"
                )
            if existing.status == IdempotencyKeyStatus.COMPLETED:
                yield IdempotencyGuard(record=existing, replayed=True, _repository=self.repository)
                return
            # FAILED -> allow a fresh attempt by reusing the same row.
            existing.status = IdempotencyKeyStatus.IN_PROGRESS
            existing.locked_at = datetime.now(timezone.utc)
            await self.session.flush()
            record = existing
        else:
            try:
                record = await self.repository.create(
                    scope=scope,
                    key=key,
                    user_id=user_id,
                    request_fingerprint=fingerprint,
                    status=IdempotencyKeyStatus.IN_PROGRESS,
                    expires_at=datetime.now(timezone.utc) + ttl,
                )
            except IntegrityError as exc:
                # Concurrent request won the race to insert the same key.
                await self.session.rollback()
                raise ConflictException(
                    "A request with this Idempotency-Key is already being processed"
                ) from exc

        guard = IdempotencyGuard(record=record, replayed=False, _repository=self.repository)
        try:
            yield guard
        except Exception:
            await guard.fail()
            raise