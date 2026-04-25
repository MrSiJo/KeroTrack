"""Argon2id password hashing helpers (JobTrack pattern, ADR-0005)."""

from __future__ import annotations

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError

_ph = PasswordHasher()


def hash_password(password: str) -> str:
    """Return an argon2id-encoded hash of `password`."""
    return _ph.hash(password)


def verify_password(password: str, hashed: str | None) -> bool:
    """Return True iff `password` verifies against `hashed`.

    Returns False on any error — including malformed hash strings — so callers
    don't have to discriminate failure modes.
    """
    if not hashed:
        return False
    try:
        return _ph.verify(hashed, password)
    except VerifyMismatchError:
        return False
    except Exception:
        return False
