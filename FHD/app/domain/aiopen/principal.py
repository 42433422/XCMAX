"""Trusted, immutable owner/tenant binding for an AIOPEN screen capability."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


def _identifier(value: Any) -> str | None:
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        return None
    normalized = str(value).strip()
    return normalized if normalized and len(normalized) <= 128 else None


@dataclass(frozen=True)
class ScreenPrincipal:
    principal_id: str
    tenant_id: str

    @classmethod
    def from_ids(cls, principal_id: Any, tenant_id: Any) -> ScreenPrincipal | None:
        owner, tenant = _identifier(principal_id), _identifier(tenant_id)
        return cls(owner, tenant) if owner is not None and tenant is not None else None

    @classmethod
    def from_user(cls, user: Any) -> ScreenPrincipal | None:
        """Only call with a server-authenticated user, never a request body."""
        if user is None or not getattr(user, "is_active", True):
            return None
        return cls.from_ids(getattr(user, "id", None), getattr(user, "tenant_id", None))

    def owns(self, metadata: dict[str, Any]) -> bool:
        return self == self.from_ids(metadata.get("principal_id"), metadata.get("tenant_id"))
