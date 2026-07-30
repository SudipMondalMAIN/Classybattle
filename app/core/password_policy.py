"""
Secure password policy enforcement.
"""
import re

from app.core.exceptions import ValidationException

MIN_LENGTH = 8
MAX_LENGTH = 128

_UPPER_RE = re.compile(r"[A-Z]")
_LOWER_RE = re.compile(r"[a-z]")
_DIGIT_RE = re.compile(r"\d")
_SPECIAL_RE = re.compile(r"[!@#$%^&*()\-_=+\[\]{};:'\",.<>/?\\|`~]")


def validate_password_strength(password: str) -> None:
    """Raises ValidationException if the password does not meet policy."""
    errors: list[str] = []

    if len(password) < MIN_LENGTH:
        errors.append(f"Password must be at least {MIN_LENGTH} characters long")
    if len(password) > MAX_LENGTH:
        errors.append(f"Password must be at most {MAX_LENGTH} characters long")
    if not _UPPER_RE.search(password):
        errors.append("Password must contain at least one uppercase letter")
    if not _LOWER_RE.search(password):
        errors.append("Password must contain at least one lowercase letter")
    if not _DIGIT_RE.search(password):
        errors.append("Password must contain at least one digit")
    if not _SPECIAL_RE.search(password):
        errors.append("Password must contain at least one special character")

    if errors:
        raise ValidationException("Password does not meet security requirements", details=errors)
