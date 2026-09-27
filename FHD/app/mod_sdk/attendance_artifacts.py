"""Per-user files served by legacy attendance download links."""

from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import unquote
from uuid import uuid4

from fastapi import HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse

from app.application.tenant_workspace_prefs import resolve_workspace_owner_id
from app.infrastructure.auth.dependencies import get_logged_in_user
from app.mod_sdk.owner_workspace import owner_workspace
from app.utils.operational_errors import RECOVERABLE_ERRORS

_MOD_ID = "attendance-artifacts"
_OUTPUT_NAME = re.compile(r"attendance-(?:output|export)-[0-9a-f]{32}\.xlsx\Z")


def owner_for_user_id(user_id: object, workspace_scope: str = "") -> str:
    try:
        value = int(str(user_id))
    except (TypeError, ValueError):
        value = 0
    if value <= 0:
        raise ValueError("authenticated local user id required")
    scope = workspace_scope or f"session:{value}"
    if not re.fullmatch(r"(?:tenant|session):[1-9][0-9]*", scope):
        raise ValueError("authenticated workspace scope required")
    return f"{scope}|user:{value}"


def owner_for_request(request: Request) -> str:
    user = get_logged_in_user(request)
    try:
        scope = resolve_workspace_owner_id(request, user)
        if not scope:
            raise ValueError("missing workspace scope")
        return owner_for_user_id(getattr(user, "id", None), scope)
    except ValueError:
        raise HTTPException(403, "无法确认考勤文件归属，请重新登录") from None


def allocate_file(owner: str, kind: str, suffix: str = ".xlsx") -> Path:
    if kind not in {"upload", "output", "export"} or suffix not in {".xlsx", ".xlsm", ".xls"}:
        raise ValueError("invalid attendance artifact kind")
    workspace = owner_workspace(_MOD_ID, owner_id=owner)
    workspace.root.mkdir(parents=True, exist_ok=True)
    return workspace.file_path(f"attendance-{kind}-{uuid4().hex}{suffix}")


def resolve_output(owner: str, relpath: str) -> Path:
    name = unquote(relpath or "").strip()
    if not _OUTPUT_NAME.fullmatch(name):
        raise ValueError("invalid attendance output")
    return owner_workspace(_MOD_ID, owner_id=owner).existing_file(name)


def serve_output(owner: str, relpath: str, *, legacy: bool = False):
    if not unquote(relpath or "").strip():
        return JSONResponse({"success": False, "error": "missing relpath"}, status_code=400)
    try:
        path = resolve_output(owner, relpath)
    except FileNotFoundError:
        return JSONResponse({"success": False, "error": "file not found"}, status_code=404)
    except ValueError:
        message = "relpath 无效" if legacy else "下载路径无效"
        return JSONResponse({"success": False, "error": message}, status_code=400)
    except RECOVERABLE_ERRORS:
        return JSONResponse({"success": False, "error": "下载路径无效"}, status_code=400)
    if not path.is_file():
        return JSONResponse({"success": False, "error": "file not found"}, status_code=404)
    return FileResponse(path=str(path), filename=path.name, media_type="application/octet-stream")
