"""
Application-wide custom exceptions.
All business/domain errors should inherit from AppException so the
global exception handler can format them consistently.
"""
from typing import Any, Optional


class AppException(Exception):
    """Base exception for all predictable, handled application errors."""

    status_code: int = 500
    error_code: str = "INTERNAL_ERROR"

    def __init__(
        self,
        message: str = "An unexpected error occurred",
        error_code: Optional[str] = None,
        status_code: Optional[int] = None,
        details: Optional[Any] = None,
    ) -> None:
        self.message = message
        self.error_code = error_code or self.error_code
        self.status_code = status_code or self.status_code
        self.details = details
        super().__init__(message)


class NotFoundException(AppException):
    status_code = 404
    error_code = "NOT_FOUND"

    def __init__(self, message: str = "Resource not found", **kwargs):
        super().__init__(message, status_code=404, error_code="NOT_FOUND", **kwargs)


class ConflictException(AppException):
    status_code = 409
    error_code = "CONFLICT"

    def __init__(self, message: str = "Resource already exists", **kwargs):
        super().__init__(message, status_code=409, error_code="CONFLICT", **kwargs)


class UnauthorizedException(AppException):
    status_code = 401
    error_code = "UNAUTHORIZED"

    def __init__(self, message: str = "Authentication required", **kwargs):
        super().__init__(message, status_code=401, error_code="UNAUTHORIZED", **kwargs)


class ForbiddenException(AppException):
    status_code = 403
    error_code = "FORBIDDEN"

    def __init__(self, message: str = "You do not have permission to do this", **kwargs):
        super().__init__(message, status_code=403, error_code="FORBIDDEN", **kwargs)


class BadRequestException(AppException):
    status_code = 400
    error_code = "BAD_REQUEST"

    def __init__(self, message: str = "Invalid request", **kwargs):
        super().__init__(message, status_code=400, error_code="BAD_REQUEST", **kwargs)


class ValidationException(AppException):
    status_code = 422
    error_code = "VALIDATION_ERROR"

    def __init__(self, message: str = "Validation failed", **kwargs):
        super().__init__(message, status_code=422, error_code="VALIDATION_ERROR", **kwargs)


class TooManyRequestsException(AppException):
    status_code = 429
    error_code = "TOO_MANY_REQUESTS"

    def __init__(self, message: str = "Too many requests, please try again later", **kwargs):
        super().__init__(message, status_code=429, error_code="TOO_MANY_REQUESTS", **kwargs)


class OTPException(AppException):
    status_code = 400
    error_code = "OTP_ERROR"

    def __init__(self, message: str = "OTP verification failed", **kwargs):
        super().__init__(message, status_code=400, error_code="OTP_ERROR", **kwargs)


class InvalidCredentialsException(AppException):
    status_code = 401
    error_code = "INVALID_CREDENTIALS"

    def __init__(self, message: str = "Invalid email or password", **kwargs):
        super().__init__(message, status_code=401, error_code="INVALID_CREDENTIALS", **kwargs)


class ExternalServiceException(AppException):
    status_code = 502
    error_code = "EXTERNAL_SERVICE_ERROR"

    def __init__(self, message: str = "An external service failed", **kwargs):
        super().__init__(message, status_code=502, error_code="EXTERNAL_SERVICE_ERROR", **kwargs)
