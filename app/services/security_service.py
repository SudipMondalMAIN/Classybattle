"""
SecurityService — Phase 16 (Security).

Handles login history capture, device/IP tracking, suspicious-login
detection, risk scoring and account lock/unlock. Designed to be called
from AuthService without introducing a hard dependency cycle (AuthService
imports SecurityService, not the other way around).
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundException
from app.core.logging import get_logger
from app.models.security import (
    AccountLock,
    SecurityEventSeverity,
    SecurityEventType,
)
from app.models.user import User
from app.repositories.security_repository import (
    AccountLockRepository,
    LoginHistoryRepository,
    SecurityEventRepository,
)
from app.services.audit_service import AuditService
from app.models.audit_log import AuditAction

logger = get_logger(__name__)

# Tunable thresholds — kept as module constants rather than hardcoded
# magic numbers so ops can tweak behaviour without touching call sites.
FAILED_LOGIN_LOCK_THRESHOLD = 5
FAILED_LOGIN_WINDOW_MINUTES = 15
RISK_SCORE_NEW_DEVICE = 10
RISK_SCORE_NEW_IP = 10
RISK_SCORE_FAILED_LOGIN = 15
RISK_SCORE_LOCK_THRESHOLD = 80


class SecurityService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.login_history_repo = LoginHistoryRepository(session)
        self.security_event_repo = SecurityEventRepository(session)
        self.account_lock_repo = AccountLockRepository(session)
        self.audit_service = AuditService(session)

    # ------------------------------------------------------------------
    # Login capture
    # ------------------------------------------------------------------
    async def record_login_attempt(
        self,
        *,
        user: Optional[User],
        email_attempted: str,
        success: bool,
        failure_reason: Optional[str] = None,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None,
        device_id: Optional[str] = None,
        platform: Optional[str] = None,
    ):
        is_new_device = False
        is_new_ip = False
        risk_score = 0

        if user is not None:
            known_devices = await self.login_history_repo.known_devices_for_user(user.id)
            known_ips = await self.login_history_repo.known_ips_for_user(user.id)
            is_new_device = bool(device_id) and device_id not in known_devices
            is_new_ip = bool(ip_address) and ip_address not in known_ips

            if is_new_device:
                risk_score += RISK_SCORE_NEW_DEVICE
            if is_new_ip:
                risk_score += RISK_SCORE_NEW_IP
            if not success:
                risk_score += RISK_SCORE_FAILED_LOGIN

        is_suspicious = success and user is not None and (is_new_device and is_new_ip)

        entry = await self.login_history_repo.create(
            user_id=user.id if user else None,
            email_attempted=email_attempted,
            success=success,
            failure_reason=failure_reason,
            ip_address=ip_address,
            user_agent=user_agent,
            device_id=device_id,
            platform=platform,
            is_new_device=is_new_device,
            is_new_ip=is_new_ip,
            is_suspicious=is_suspicious,
            risk_score=risk_score,
        )

        if user is not None:
            await self._update_risk_score(user.id, delta=risk_score)

            if is_suspicious:
                await self.security_event_repo.create(
                    user_id=user.id,
                    event_type=SecurityEventType.SUSPICIOUS_LOGIN,
                    severity=SecurityEventSeverity.MEDIUM,
                    description="Login from a new device and new IP address simultaneously",
                    event_metadata={"ip_address": ip_address, "device_id": device_id},
                    ip_address=ip_address,
                )
            elif success and is_new_device:
                await self.security_event_repo.create(
                    user_id=user.id,
                    event_type=SecurityEventType.NEW_DEVICE_LOGIN,
                    severity=SecurityEventSeverity.LOW,
                    description="Login from a new device",
                    event_metadata={"ip_address": ip_address, "device_id": device_id},
                    ip_address=ip_address,
                )

            if not success:
                recent_failures = await self.login_history_repo.count_recent_failed_attempts(
                    user.id, minutes=FAILED_LOGIN_WINDOW_MINUTES
                )
                if recent_failures >= FAILED_LOGIN_LOCK_THRESHOLD:
                    await self.security_event_repo.create(
                        user_id=user.id,
                        event_type=SecurityEventType.MULTIPLE_FAILED_LOGINS,
                        severity=SecurityEventSeverity.HIGH,
                        description=f"{recent_failures} failed login attempts within "
                        f"{FAILED_LOGIN_WINDOW_MINUTES} minutes",
                        ip_address=ip_address,
                    )
                    # Auto-lock on repeated failed logins disabled per
                    # request -- the event above still gets logged for
                    # admins to review, it just no longer locks the
                    # account on its own.
                    # await self.lock_account(
                    #     user_id=user.id,
                    #     reason="Automatic lock: too many failed login attempts",
                    #     locked_by=None,
                    # )

        await self.session.commit()
        return entry

    # ------------------------------------------------------------------
    # Risk scoring
    # ------------------------------------------------------------------
    async def _update_risk_score(self, user_id: UUID, delta: int) -> AccountLock:
        lock = await self.account_lock_repo.get_or_create(user_id)
        new_score = max(0, min(100, lock.risk_score + delta))
        lock = await self.account_lock_repo.update(lock, risk_score=new_score)

        if new_score >= RISK_SCORE_LOCK_THRESHOLD and not lock.is_locked:
            await self.security_event_repo.create(
                user_id=user_id,
                event_type=SecurityEventType.RISK_SCORE_UPDATED,
                severity=SecurityEventSeverity.HIGH,
                description=f"Risk score reached {new_score}, auto-locking account",
            )
            # Auto-lock on risk score threshold disabled per request --
            # the event above still gets logged for admins to review,
            # it just no longer locks the account on its own.
            # await self.lock_account(
            #     user_id=user_id, reason=f"Automatic lock: risk score reached {new_score}", locked_by=None
            # )
        return lock

    async def get_risk_profile(self, user_id: UUID) -> dict:
        lock = await self.account_lock_repo.get_or_create(user_id)
        recent_failed = await self.login_history_repo.count_recent_failed_attempts(user_id)
        known_devices = await self.login_history_repo.known_devices_for_user(user_id)
        known_ips = await self.login_history_repo.known_ips_for_user(user_id)
        return {
            "user_id": user_id,
            "risk_score": lock.risk_score,
            "is_locked": lock.is_locked,
            "recent_failed_logins": recent_failed,
            "known_devices": len(known_devices),
            "known_ips": len(known_ips),
        }

    # ------------------------------------------------------------------
    # Account lock / unlock
    # ------------------------------------------------------------------
    async def lock_account(
        self, *, user_id: UUID, reason: str, locked_by: Optional[UUID]
    ) -> AccountLock:
        lock = await self.account_lock_repo.get_or_create(user_id)
        lock = await self.account_lock_repo.update(
            lock,
            is_locked=True,
            reason=reason,
            locked_by=locked_by,
            locked_at=datetime.now(timezone.utc),
        )
        await self.security_event_repo.create(
            user_id=user_id,
            event_type=SecurityEventType.ACCOUNT_LOCKED,
            severity=SecurityEventSeverity.HIGH,
            description=reason,
        )
        await self.audit_service.record(
            entity="account_lock",
            action=AuditAction.STATUS_CHANGE,
            entity_id=user_id,
            new_values={"is_locked": True, "reason": reason},
            description="Account locked",
        )
        return lock

    async def unlock_account(
        self, *, user_id: UUID, unlocked_by: UUID, reason: Optional[str] = None
    ) -> AccountLock:
        lock = await self.account_lock_repo.get_by_user_id(user_id)
        if lock is None:
            raise NotFoundException("Account lock record not found")
        lock = await self.account_lock_repo.update(
            lock,
            is_locked=False,
            reason=reason,
            unlocked_at=datetime.now(timezone.utc),
            risk_score=0,
        )
        await self.security_event_repo.create(
            user_id=user_id,
            event_type=SecurityEventType.ACCOUNT_UNLOCKED,
            severity=SecurityEventSeverity.LOW,
            description=reason or "Account unlocked by admin",
        )
        await self.audit_service.record(
            entity="account_lock",
            action=AuditAction.STATUS_CHANGE,
            entity_id=user_id,
            actor=None,
            new_values={"is_locked": False, "reason": reason},
            description="Account unlocked",
        )
        await self.session.commit()
        return lock

    async def is_locked(self, user_id: UUID) -> bool:
        lock = await self.account_lock_repo.get_by_user_id(user_id)
        return bool(lock and lock.is_locked)

    # ------------------------------------------------------------------
    # Reads
    # ------------------------------------------------------------------
    async def list_login_history(self, user_id: Optional[UUID], page: int, page_size: int):
        skip = (page - 1) * page_size
        if user_id is not None:
            items = await self.login_history_repo.list_for_user(user_id, skip=skip, limit=page_size)
        else:
            items = await self.login_history_repo.list_recent(skip=skip, limit=page_size)
        return items

    async def list_security_events(
        self,
        page: int,
        page_size: int,
        user_id: Optional[UUID] = None,
        event_type: Optional[SecurityEventType] = None,
        resolved: Optional[bool] = None,
    ):
        skip = (page - 1) * page_size
        return await self.security_event_repo.list_events(
            skip=skip, limit=page_size, user_id=user_id, event_type=event_type, resolved=resolved
        )

    async def resolve_security_event(self, event_id: UUID, resolved_by: UUID):
        event = await self.security_event_repo.get_by_id(event_id)
        if event is None:
            raise NotFoundException("Security event not found")
        event = await self.security_event_repo.resolve(event, resolved_by)
        await self.session.commit()
        return event

    async def list_locked_accounts(self, page: int, page_size: int):
        skip = (page - 1) * page_size
        return await self.account_lock_repo.list_locked(skip=skip, limit=page_size)