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


def main() -> int:
    conn = psycopg2.connect(settings.DATABASE_URL_SYNC)
    conn.autocommit = True
    try:
        with conn.cursor() as cur:
            print("Waiting for migration lock...", flush=True)
            cur.execute("SELECT pg_advisory_lock(%s)", (MIGRATION_LOCK_KEY,))
            print("Migration lock acquired, running alembic upgrade head", flush=True)

        result = subprocess.run(["alembic", "upgrade", "head"])

        with conn.cursor() as cur:
            cur.execute("SELECT pg_advisory_unlock(%s)", (MIGRATION_LOCK_KEY,))

        return result.returncode
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
