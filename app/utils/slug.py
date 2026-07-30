"""
URL-safe slug generation utilities.
"""
import re
import uuid

_SLUG_RE = re.compile(r"[^a-z0-9]+")


def slugify(value: str) -> str:
    """Convert arbitrary text into a lowercase, hyphen-separated slug."""
    value = value.strip().lower()
    value = _SLUG_RE.sub("-", value)
    return value.strip("-") or "item"


def generate_unique_suffix() -> str:
    """Short random suffix used to disambiguate colliding slugs."""
    return uuid.uuid4().hex[:6]
