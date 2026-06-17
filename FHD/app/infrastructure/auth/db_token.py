"""Database token compatibility shims.

The product no longer uses database read/write password gates. The public
functions remain so older route modules can import them without reintroducing
authorization prompts or token checks.
"""

from __future__ import annotations

from fastapi import Request


def configured_db_read_token(active_mod_id: str | None = None) -> str | None:
    _ = active_mod_id
    return None


def effective_db_read_token() -> str | None:
    return None


def verify_db_read_token_header(request: Request) -> None:
    _ = request
    return None


def configured_db_write_token(active_mod_id: str | None = None) -> str | None:
    _ = active_mod_id
    return None


def verify_db_write_token_header(request: Request) -> None:
    _ = request
    return None


__all__ = [
    "configured_db_read_token",
    "effective_db_read_token",
    "verify_db_read_token_header",
    "configured_db_write_token",
    "verify_db_write_token_header",
]
