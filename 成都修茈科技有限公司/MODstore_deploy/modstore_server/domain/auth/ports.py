"""Auth persistence ports."""

from __future__ import annotations

from typing import Protocol

from modstore_server.domain.auth.types import PersonalAccessToken


class PersonalAccessTokenRepository(Protocol):
    def save(self, row: PersonalAccessToken, *, token_digest: str, raw_prefix: str) -> int:
        """Persist and return token row id."""

    def revoke(self, *, user_id: int, token_id: int) -> bool: ...


__all__ = ["PersonalAccessTokenRepository"]
