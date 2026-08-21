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

IMPORTANT — Redis outage resilience
------------------------------------
By default slowapi does NOT handle a dead/unreachable Redis gracefully:
when the storage backend raises (e.g. redis.exceptions.ConnectionError
on a dropped connection), that raw exception bubbles out of
`limiter._check_request_limit` and slowapi's middleware hands it to
`_rate_limit_exceeded_handler`, which unconditionally does `exc.detail`.
A ConnectionError has no `.detail`, so a Redis blip turns into an
unhandled `AttributeError: 'ConnectionError' object has no attribute
'detail'` and every request 500s until Redis recovers.

Two slowapi options fix this:
  - in_memory_fallback_enabled: on a storage error, slowapi
    automatically switches that worker to an in-memory limiter (using
    in_memory_fallback, or default_limits if that list is empty) and
    keeps polling the real storage in the background, switching back
    once it recovers. This is the primary fix — requests keep flowing
    during a Redis outage instead of crashing.
  - swallow_errors: belt-and-suspenders. If somehow a storage error
    still isn't handled by the fallback path above, log it and let the
    request through instead of raising.
"""
from slowapi import Limiter

from app.config.settings import settings
from app.core.client_ip import resolve_client_ip_for_limiter

_default_limit = f"{settings.RATE_LIMIT_PER_MINUTE}/minute"

limiter = Limiter(
    key_func=resolve_client_ip_for_limiter,
    default_limits=[_default_limit],
    storage_uri=settings.REDIS_URL or None,
    in_memory_fallback_enabled=True,
    in_memory_fallback=[_default_limit],
    swallow_errors=True,
)