"""
Global API rate limiting using slowapi.

IMPORTANT — shared storage across workers
------------------------------------------
The production process runs multiple uvicorn workers (see
docker-compose.prod.yml, --workers 4). slowapi's default storage is an
in-memory dict *per process*, so without an explicit shared backend each
worker enforces the configured limit independently — a client rotated
across workers by the OS/load balancer could effectively get
(configured limit x worker count) requests through.

Setting REDIS_URL makes every worker share one counter, so e.g.
AUTH_RATE_LIMIT="10/minute" is genuinely 10/minute per IP, not 40.
If REDIS_URL is unset, this falls back to in-memory storage — fine for
local single-worker development, but do not run production without
REDIS_URL configured.
"""
from slowapi import Limiter

from app.config.settings import settings
from app.core.client_ip import resolve_client_ip_for_limiter

limiter = Limiter(
    key_func=resolve_client_ip_for_limiter,
    default_limits=[f"{settings.RATE_LIMIT_PER_MINUTE}/minute"],
    storage_uri=settings.REDIS_URL or None,
)
