"""
Runs `alembic upgrade head` guarded by a Postgres advisory lock.

Why this exists
----------------
The container CMD runs `alembic upgrade head` on every boot. During a
Render rolling deploy (or any deploy with >1 instance/replica), the old
and new instances can briefly run at the same time, so two processes can
call `alembic upgrade head` concurrently. Alembic's own bookkeeping
(alembic_version table) does not protect against this: both processes see
the same "not yet applied" state, both try to run migration 0002, and the
second `CREATE TYPE tournament_status ...` fails with
`DuplicateObjectError: type "tournament_status" already exists`, even
though the migration uses `checkfirst=True` (checkfirst only prevents
re-running an *already applied* migration — it does not prevent two
processes racing through the *same* not-yet-applied migration).

Fix: take a session-level Postgres advisory lock before running Alembic.
The first process to connect gets the lock and runs migrations normally.
Any other process blocks on the lock until the first one finishes and
disconnects (which releases the lock automatically), then it runs
Alembic itself — by that point the migration is already applied, so
Alembic just sees "nothing to do" and exits cleanly.
"""
import subprocess
import sys

import psycopg2

from app.config.settings import settings

# Arbitrary fixed 64-bit key, unique to this app, used for the advisory lock.
# Any two processes calling pg_advisory_lock with the same key will
# serialize against each other.
MIGRATION_LOCK_KEY = 875_142_339_001


def _to_psycopg2_dsn(url: str) -> str:
    # psycopg2.connect() doesn't understand SQLAlchemy-style driver suffixes
    # like "postgresql+psycopg2://" — it only accepts "postgresql://".
    if url.startswith("postgresql+psycopg2://"):
        return "postgresql://" + url[len("postgresql+psycopg2://"):]
    return url


def _widen_version_column_if_exists(conn) -> None:
    # Alembic creates alembic_version.version_num as VARCHAR(32) by default.
    # All revision ids in this repo are now kept under that limit, but we
    # still widen the column defensively (e.g. for old databases stuck with
    # a pre-fix narrow column, or future revision ids that creep past 32
    # chars), which makes Postgres raise StringDataRightTruncationError when
    # Alembic tries to write a version that doesn't fit. No-op if the table
    # doesn't exist yet (fresh DB, before Alembic's first run) or is already
    # wide enough.
    with conn.cursor() as cur:
        cur.execute(
            """
            DO $$
            BEGIN
                IF EXISTS (
                    SELECT 1 FROM information_schema.tables
                    WHERE table_name = 'alembic_version'
                ) THEN
                    ALTER TABLE alembic_version
                        ALTER COLUMN version_num TYPE VARCHAR(255);
                END IF;
            END
            $$;
            """
        )


def main() -> int:
    conn = psycopg2.connect(_to_psycopg2_dsn(settings.DATABASE_URL_SYNC))
    conn.autocommit = True
    try:
        with conn.cursor() as cur:
            print("Waiting for migration lock...", flush=True)
            cur.execute("SELECT pg_advisory_lock(%s)", (MIGRATION_LOCK_KEY,))
            print("Migration lock acquired, running alembic upgrade head", flush=True)

        # Widen up front for the common case (table already exists from a
        # previous deploy).
        _widen_version_column_if_exists(conn)

        result = subprocess.run(["alembic", "upgrade", "head"])

        if result.returncode != 0:
            # Covers the fresh-DB case: alembic_version didn't exist yet on
            # the first pass above, so Alembic created it with the narrow
            # VARCHAR(32) default itself while applying 0001. Widen it now
            # that it exists and retry once.
            print("alembic upgrade failed, widening alembic_version and retrying once", flush=True)
            _widen_version_column_if_exists(conn)
            result = subprocess.run(["alembic", "upgrade", "head"])

        with conn.cursor() as cur:
            cur.execute("SELECT pg_advisory_unlock(%s)", (MIGRATION_LOCK_KEY,))

        return result.returncode
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())