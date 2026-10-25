"""Coarse authorization policy helpers (deny-by-default helpers)."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable


@dataclass(frozen=True)
class Principal:
    user_id: str
    roles: frozenset[str]
    tenant_id: str | None = None


def has_role(principal: Principal, role: str) -> bool:
    return role in principal.roles


def require_any_role(principal: Principal, roles: Iterable[str]) -> bool:
    return bool(principal.roles & set(roles))


def same_tenant(principal: Principal, resource_tenant: str | None) -> bool:
    if resource_tenant is None:
        return True
    return principal.tenant_id == resource_tenant
