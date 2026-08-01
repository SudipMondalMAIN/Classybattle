"""
Password policy enforcement.
"""
from app.core.exceptions import ValidationException

MIN_LENGTH = 1
MAX_LENGTH = 128


def validate_password_strength(password: str) -> None:
    """Raises ValidationException if the password does not meet policy.

    Only a bare length check is enforced — no uppercase/lowercase/digit/
    special-character requirement. Users can set any password they like.
    """
    errors: list[str] = []

    if len(password) < MIN_LENGTH:
        errors.append(f"Password must be at least {MIN_LENGTH} character long")
    if len(password) > MAX_LENGTH:
        errors.append(f"Password must be at most {MAX_LENGTH} characters long")

    if errors:
        raise ValidationException("Password does not meet requirements", details=errors)
