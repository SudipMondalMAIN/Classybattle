"""
Transaction number generation — 10-digit numeric TXN IDs used on
PaymentRequest (deposit) and WithdrawalRequest (withdrawal) rows.

Uses `secrets` (not `random`) since these are user-facing money
references and should not be predictable. Uniqueness is verified
against the DB with a bounded retry loop; the column also carries a
UNIQUE constraint as the real guarantee under concurrency.
"""
import secrets
from typing import Type, TypeVar

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import DeclarativeBase

_DIGITS = "0123456789"
_NONZERO_DIGITS = "123456789"

ModelT = TypeVar("ModelT", bound=DeclarativeBase)


def _random_txn_no() -> str:
    """A 10-digit numeric string that never starts with 0."""
    return secrets.choice(_NONZERO_DIGITS) + "".join(
        secrets.choice(_DIGITS) for _ in range(9)
    )


async def generate_unique_txn_no(
    session: AsyncSession,
    model: Type[ModelT],
    *,
    field: str = "txn_no",
    max_attempts: int = 8,
) -> str:
    """Generate a 10-digit numeric TXN no that doesn't already exist on
    `model`. Raises RuntimeError if it can't find a free one within
    `max_attempts` (astronomically unlikely with a 9e9-sized space)."""
    column = getattr(model, field)
    for _ in range(max_attempts):
        candidate = _random_txn_no()
        result = await session.execute(select(column).where(column == candidate))
        if result.scalar_one_or_none() is None:
            return candidate
    raise RuntimeError(
        f"Could not generate a unique txn_no for {model.__tablename__} "
        f"after {max_attempts} attempts"
    )
