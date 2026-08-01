"""
Shared, trusted-proxy-aware client IP resolution.

Used by the rate limiter, request logging middleware, and (indirectly, via
`app.core.request_context`) the audit-log / security services, so that every
part of the application agrees on a single client IP for a given request.

Why this exists
----------------
`X-Forwarded-For` can contain an arbitrary, attacker-supplied list of
addresses (a client can send `X-Forwarded-For: 1.2.3.4` itself). Naively
trusting the left-most entry lets a client spoof any IP it wants and evade
IP-based rate limiting / bans.

When the app runs behind a reverse proxy (Render, nginx, etc.) there is
exactly one hop we trust: the proxy in front of us. That proxy appends the
real connecting peer's address as the *last* entry in `X-Forwarded-For`
(or sets it fresh if the header didn't exist yet). Untrusted, client-supplied
values end up further to the left. So the safe address to use is the
`TRUSTED_PROXY_COUNT`-th entry counting from the right, not the left.

`TRUSTED_PROXY_COUNT` defaults to 1 (a single reverse proxy in front of the
app, which matches a standard Render deployment). If more proxies are added
in front of the app later, bump this setting accordingly instead of trusting
the header blindly.
"""
from __future__ import annotations

from typing import Optional

from starlette.requests import Request

from app.config.settings import settings


def resolve_client_ip(request: Request) -> Optional[str]:
    """Resolve the real client IP for `request`, resistant to XFF spoofing.

    - If `X-Forwarded-For` is present, take the entry `TRUSTED_PROXY_COUNT`
      hops from the right (the address appended by our own trusted proxy).
      Anything to the left of that is client-controlled and never trusted.
    - Otherwise, fall back to the direct socket peer address.
    """
    forwarded_for = request.headers.get("x-forwarded-for")
    trusted_hops = max(settings.TRUSTED_PROXY_COUNT, 0)

    if forwarded_for and trusted_hops > 0:
        parts = [addr.strip() for addr in forwarded_for.split(",") if addr.strip()]
        if len(parts) >= trusted_hops:
            return parts[-trusted_hops]
        if parts:
            # Fewer hops than expected (e.g. local/dev proxy chain) —
            # fall back to the left-most known entry rather than nothing.
            return parts[0]

    return request.client.host if request.client else None


def resolve_client_ip_for_limiter(request: Request) -> str:
    """slowapi `key_func` adapter — same resolution logic, non-optional string."""
    return resolve_client_ip(request) or "unknown"
