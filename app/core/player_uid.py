"""
Player UID generator.

Every user gets a short, unique, numeric public ID (e.g. "48213067") that
players can share/search by — much easier to read out loud, type on a
phone keypad, or remember than a UUID or an email/phone lookup.

Format: exactly 8 digits (0-9), zero-padded, generated with a
cryptographically secure RNG.
"""
import secrets

_NUM_DIGITS = 8


def generate_player_uid() -> str:
    """Generate a single candidate 8-digit player UID. Caller is
    responsible for checking uniqueness against the database and
    retrying on collision."""
    number = secrets.randbelow(10**_NUM_DIGITS)
    return str(number).zfill(_NUM_DIGITS)

