"""
Request-scoped context propagation.

FastAPI/Starlette handlers, services and repositories run inside the same
asyncio task for the lifetime of a single request, so `contextvars` let us
thread request metadata (request id, client IP) through the call stack
without changing every function signature. This is what powers the audit
logging system (Phase 7.5 item 3) and is safe under concurrent requests
because each request gets its own `Token`-scoped context.
"""
from __future__ import annotations

from contextvars import ContextVar, Token
from typing import Optional

_request_id_var: ContextVar[Optional[str]] = ContextVar("request_id", default=None)
_client_ip_var: ContextVar[Optional[str]] = ContextVar("client_ip", default=None)


def set_request_context(*, request_id: Optional[str], client_ip: Optional[str]) -> tuple[Token, Token]:
    """Bind request metadata to the current context. Returns tokens for reset."""
    token_request_id = _request_id_var.set(request_id)
    token_client_ip = _client_ip_var.set(client_ip)
    return token_request_id, token_client_ip


def reset_request_context(tokens: tuple[Token, Token]) -> None:
    token_request_id, token_client_ip = tokens
    _request_id_var.reset(token_request_id)
    _client_ip_var.reset(token_client_ip)


def get_request_id() -> Optional[str]:
    return _request_id_var.get()


def get_client_ip() -> Optional[str]:
    return _client_ip_var.get()
