"""Passwords (IAM-03, ADR-0016): Argon2id hashes, the rules a new password must pass, and
temporary passwords.

A new password needs at least 12 characters, mustn't be on the offline breached-password list
(breached-passwords.txt.gz, see its NOTICE), and mustn't be one of the account's last five or
the temporary password it replaces. Temporary passwords are random and work for 24 h.
"""

from __future__ import annotations

import gzip
import secrets
from functools import lru_cache
from pathlib import Path

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

from ..settings import AuthSettings

BREACHED = Path(__file__).with_name("breached-passwords.txt.gz")
MAX_LENGTH = 256  # beyond this, hashing only wastes time
ALPHABET = "abcdefghjkmnpqrstuvwxyz23456789"  # no 0/o or 1/l/i: temporary passwords are read out or copied


@lru_cache(maxsize=1)
def breached() -> frozenset[str]:
    """The list, lower-cased: the check ignores case."""
    with gzip.open(BREACHED, "rt", encoding="utf-8") as f:
        return frozenset(word for word in f.read().split("\n") if word)


class Passwords:
    def __init__(self, s: AuthSettings):
        self.settings = s
        self.hasher = PasswordHasher(time_cost=s.argon2_time_cost, memory_cost=s.argon2_memory_kib,
                                     parallelism=s.argon2_parallelism)
        # Checked when no account has the name, so a wrong name takes as long as a wrong password
        self._dummy = self.hasher.hash(secrets.token_urlsafe(16))

    def hash(self, password: str) -> str:
        return self.hasher.hash(password)

    def verify(self, stored: str | None, password: str) -> bool:
        try:
            ok = self.hasher.verify(stored or self._dummy, password[:MAX_LENGTH])
        except (VerificationError, InvalidHashError):
            return False
        return ok and stored is not None

    def needs_rehash(self, stored: str) -> bool:
        return self.hasher.check_needs_rehash(stored)

    def problems(self, password: str, current: str | None, previous: list[str]) -> list[str]:
        """Why a new password can't be used; empty when it can. `previous`: the account's chosen passwords, newest first."""
        s = self.settings
        if len(password) < s.password_min_length:
            return [f"Use at least {s.password_min_length} characters"]
        if len(password) > MAX_LENGTH:
            return [f"Use at most {MAX_LENGTH} characters"]
        out = []
        if password.lower() in breached():
            out.append("This password is on the list of passwords known from breaches: choose another")
        if self.verify(current, password):
            out.append("Choose a new password, not the one you have now")
        elif any(self.verify(h, password) for h in previous[: s.password_history]):
            out.append(f"You've used this password before: choose one that isn't among your last {s.password_history}")
        return out

    @staticmethod
    def temporary() -> str:
        """16 random characters in groups of four, e.g. k7mq-x2pt-9hwz-r4cd (about 79 bits)."""
        chars = "".join(secrets.choice(ALPHABET) for _ in range(16))
        return "-".join(chars[i:i + 4] for i in range(0, 16, 4))
