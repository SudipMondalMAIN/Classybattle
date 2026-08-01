"""
Middleware for structured request/response logging.
"""
import time
import uuid

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

from app.core.client_ip import resolve_client_ip
from app.core.logging import get_logger
from app.core.request_context import reset_request_context, set_request_context

logger = get_logger("http")


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        request_id = str(uuid.uuid4())
        client_ip = resolve_client_ip(request)
        start_time = time.perf_counter()

        context_tokens = set_request_context(request_id=request_id, client_ip=client_ip)

        response = None
        try:
            response = await call_next(request)
            return response
        finally:
            duration_ms = round((time.perf_counter() - start_time) * 1000, 2)
            status_code = response.status_code if response else 500
            logger.info(
                "http_request",
                request_id=request_id,
                method=request.method,
                path=request.url.path,
                status_code=status_code,
                duration_ms=duration_ms,
                client=client_ip,
            )
            if response is not None:
                response.headers["X-Request-ID"] = request_id
            reset_request_context(context_tokens)
