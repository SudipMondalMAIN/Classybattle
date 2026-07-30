"""
Portable column types shared across models.
"""
from sqlalchemy import JSON
from sqlalchemy.dialects.postgresql import JSONB as PG_JSONB
from sqlalchemy.types import TypeDecorator

# JSONB is a Postgres-only dialect type. Production/staging always run on
# Postgres, but the automated test suite (tests/conftest.py) uses an
# in-memory SQLite database for speed/isolation, and SQLAlchemy's SQLite
# dialect cannot compile a raw postgresql.JSONB column. `with_variant`
# swaps in the generic JSON type only when the active dialect is sqlite,
# so production behaviour (indexed JSONB) is completely unchanged.
PortableJSONB = PG_JSONB().with_variant(JSON(), "sqlite")
