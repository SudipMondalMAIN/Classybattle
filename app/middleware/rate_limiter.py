"""
Global API rate limiting using slowapi.
"""
from slowapi import Limiter

from app.config.settings import settings
from app.core.client_ip import resolve_client_ip_for_limiter

limiter = Limiter(
    key_func=resolve_client_ip_for_limiter,
    default_limits=[f"{settings.RATE_LIMIT_PER_MINUTE}/minute"],
)
