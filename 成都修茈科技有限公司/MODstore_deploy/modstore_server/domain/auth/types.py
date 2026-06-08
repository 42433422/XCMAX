"""Auth domain value objects (logical; ORM ``User`` 仍在平台层)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Optional


@dataclass(frozen=True)
class AccessTokenClaims:
    user_id: int
    username: str
    is_admin: bool = False


@dataclass(frozen=True)
class PersonalAccessToken:
    token_id: int
    user_id: int
    name: str
    prefix: str
    scopes: tuple[str, ...]
    expires_at: Optional[datetime] = None
