"""
Referral code generator.

Short, unique, human-typeable code every user gets (e.g. "K7F9QX2A").
Uppercase letters + digits only, ambiguous characters (0/O, 1/I/L)
excluded so it's easy to read out loud / type on a phone keyboard.
"""
import secrets

_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"  # no 0/O/1/I/L
_LENGTH = 8


def generate_referral_code() -> str:
    """Generate a single candidate referral code. Caller is responsible
    for checking uniqueness against the database and retrying on
    collision."""
    return "".join(secrets.choice(_ALPHABET) for _ in range(_LENGTH))
