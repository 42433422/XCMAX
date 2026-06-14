"""RBAC Pydantic 模型。"""

from __future__ import annotations

from pydantic import BaseModel, Field


class RoleCreate(BaseModel):
    name: str = Field(..., min_length=1)
    description: str | None = None
    permissions: list[str] = Field(default_factory=list)


class RoleUpdate(BaseModel):
    description: str | None = None
    permissions: list[str] | None = None


class PermissionCreate(BaseModel):
    code: str = Field(..., min_length=1)
    name: str = Field(..., min_length=1)
    description: str | None = None
    module: str | None = None


class UserRoleAssign(BaseModel):
    role: str = Field(..., min_length=1)
