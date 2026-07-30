"""
OTP generation and hashing utilities.
"""
import secrets

from passlib.context import CryptContext

from app.config.settings import settings

_otp_hash_context = CryptContext(schemes=["sha256_crypt"], deprecated="auto")


def generate_numeric_otp(length: int | None = None) -> str:
    """Generate a cryptographically secure numeric OTP."""
    length = length or settings.OTP_LENGTH
    return "".join(str(secrets.randbelow(10)) for _ in range(length))


def hash_otp(otp: str) -> str:
    return _otp_hash_context.hash(otp)


def verify_otp_hash(otp: str, otp_hash: str) -> bool:
    return _otp_hash_context.verify(otp, otp_hash)
