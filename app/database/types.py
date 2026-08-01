"""
Portable column types shared across models.
"""
from sqlalchemy import JSON, Enum
from sqlalchemy.dialects.postgresql import JSONB as PG_JSONB

# JSONB is a Postgres-only dialect type. Production/staging always run on
# Postgres, but the automated test suite (tests/conftest.py) uses an
# in-memory SQLite database for speed/isolation, and SQLAlchemy's SQLite
# dialect cannot compile a raw postgresql.JSONB column. `with_variant`
# swaps in the generic JSON type only when the active dialect is sqlite,
# so production behaviour (indexed JSONB) is completely unchanged.
PortableJSONB = PG_JSONB().with_variant(JSON(), "sqlite")


def str_enum(enum_cls, name: str, **kwargs) -> Enum:
    """
    Build a SQLAlchemy Enum column type that sends each member's `.value`
    (e.g. "user") to the database instead of SQLAlchemy's default of the
    member's `.name` (e.g. "USER"). Our Postgres enum types are always
    created with lowercase labels (see migrations), so every str-Enum
    column in this codebase must use this helper instead of calling
    sqlalchemy.Enum(...) directly, or inserts will fail with
    InvalidTextRepresentationError.
    """
    return Enum(
        enum_cls,
        name=name,
        values_callable=lambda cls: [member.value for member in cls],
        **kwargs,
    )
