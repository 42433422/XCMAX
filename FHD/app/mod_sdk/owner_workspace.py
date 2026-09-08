"""Authenticated, owner-scoped storage for independently installed Mods.

The owner comes from the normal session contract. Legacy process-wide data is
never claimed, copied, or inferred from a customer name by this API.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import AsyncIterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from pathlib import Path

from fastapi import HTTPException, Request

from app.application.tenant_workspace_prefs import resolve_workspace_owner_id
from app.infrastructure.auth.dependencies import get_logged_in_user
from app.infrastructure.workspace import resolve_existing_file_under_root, workspace_root

_current_owner: ContextVar[str | None] = ContextVar("mod_workspace_owner", default=None)
_MOD_ID = re.compile(r"[a-z0-9][a-z0-9_-]{0,95}\Z")


def validate_mod_id(mod_id: str) -> str:
    if not isinstance(mod_id, str) or not _MOD_ID.fullmatch(mod_id):
        raise HTTPException(400, "无效的扩展包编号")
    return mod_id


def authenticated_owner(request: Request) -> str:
    user = get_logged_in_user(request)
    owner = resolve_workspace_owner_id(request, user)
    if not owner:
        raise HTTPException(403, "无法确认数据归属，请重新登录")
    return owner


async def require_owner_workspace(request: Request) -> AsyncIterator[str]:
    owner = authenticated_owner(request)
    with owner_context(owner):
        yield owner


@contextmanager
def owner_context(owner: str):
    """Bind an already authenticated owner for an in-process Mod invocation."""
    if not owner:
        raise HTTPException(401, "请先登录后访问扩展数据")
    token = _current_owner.set(owner)
    try:
        yield owner
    finally:
        _current_owner.reset(token)


@dataclass(frozen=True)
class OwnerWorkspace:
    owner_id: str
    mod_id: str
    root: Path

    def existing_file(self, relative_path: str) -> Path:
        return resolve_existing_file_under_root(self.root, relative_path)

    def file_path(self, filename: str) -> Path:
        """A code-defined single filename, with no implicit directory creation."""
        if not filename or filename in {".", ".."} or any(c in filename for c in "/\\\0"):
            raise ValueError("invalid workspace filename")
        candidate = self.root / filename
        if candidate.is_symlink():
            raise HTTPException(409, "扩展数据路径不可使用符号链接")
        return candidate


def owner_workspace(mod_id: str, *, owner_id: str | None = None) -> OwnerWorkspace:
    mid = validate_mod_id(mod_id)
    owner = owner_id or _current_owner.get()
    if not owner:
        raise HTTPException(401, "请先登录后访问扩展数据")
    owner_key = hashlib.sha256(owner.encode("utf-8")).hexdigest()
    base = workspace_root()
    root = base / "mod-workspaces" / owner_key / mid
    # Reject redirects through an existing symlink at every boundary, including
    # the owner directory. Do not resolve a link and then accept its target.
    current = base
    for part in ("mod-workspaces", owner_key, mid):
        current = current / part
        if current.is_symlink():
            raise HTTPException(409, "扩展数据目录不可使用符号链接")
    return OwnerWorkspace(owner_id=owner, mod_id=mid, root=root)


def attendance_database_path() -> Path:
    return owner_workspace("attendance-industry").file_path("attendance.db")
