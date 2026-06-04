"""RBAC Pydantic schemas."""

from __future__ import annotations

from pydantic import BaseModel, Field


class RoleCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    description: str = ""
    permissions: list[str] = Field(default_factory=list)


class RoleUpdate(BaseModel):
    description: str | None = None
    permissions: list[str] | None = None


class PermissionCreate(BaseModel):
    code: str = Field(..., min_length=1, max_length=100)
    name: str = Field(..., min_length=1, max_length=200)
    description: str = ""
    module: str = "custom"


class UserRoleAssign(BaseModel):
    role: str = Field(..., min_length=1, max_length=100)


class RoleSummary(BaseModel):
    id: int
    name: str
    description: str | None = None
    is_system: bool = False
    permissions: list[str] = Field(default_factory=list)


class PermissionSummary(BaseModel):
    id: int
    name: str
    code: str
    description: str | None = None
    module: str | None = None
