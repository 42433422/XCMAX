"""Serve independently compiled UI only from a verified local Mod installation."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path, PurePosixPath
from typing import Any

from fastapi import HTTPException, Request

from app.enterprise.private_delivery_binding import (
    load_session_private_delivery_binding,
)
from app.infrastructure.auth.dependencies import session_id_from_request
from app.infrastructure.workspace import resolve_existing_file_under_root
from app.mod_sdk.owner_workspace import authenticated_owner, validate_mod_id

_ASSET_TYPES = {
    ".js": "text/javascript",
    ".css": "text/css",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".woff2": "font/woff2",
}


def _verified_install(mod_id: str) -> dict[str, Any]:
    from app.infrastructure.mods.install_receipts import read_verified_install

    install = read_verified_install(validate_mod_id(mod_id))
    if not install:
        raise HTTPException(409, "扩展包尚未完成签名与安装验证")
    return install


def _verified_file(install: dict[str, Any], relative_path: str) -> bytes:
    hashes = install.get("file_sha256") or {}
    expected = hashes.get(relative_path)
    if not isinstance(expected, str) or len(expected) != 64:
        raise HTTPException(404, "扩展资源不在已验证包内")
    try:
        path = resolve_existing_file_under_root(Path(install["installed_root"]), relative_path)
        if path.stat().st_size > 20 * 1024 * 1024:
            raise HTTPException(413, "扩展资源超过大小限制")
        content = path.read_bytes()
    except (OSError, ValueError):
        raise HTTPException(409, "扩展资源缺失或路径无效") from None
    if hashlib.sha256(content).hexdigest() != expected:
        raise HTTPException(409, "扩展资源已变化，请重新安装已验证版本")
    return content


def authorized_install(request: Request, mod_id: str) -> tuple[dict[str, Any], dict[str, Any], str]:
    owner = authenticated_owner(request)
    install = _verified_install(mod_id)
    if install.get("requires_restart"):
        raise HTTPException(409, "扩展已安装，请重启客户端后使用新版本")
    try:
        manifest = json.loads(_verified_file(install, "manifest.json"))
    except (ValueError, TypeError):
        raise HTTPException(409, "扩展清单无效") from None
    if not isinstance(manifest, dict) or manifest.get("id") != mod_id:
        raise HTTPException(409, "扩展身份不匹配")
    if str(manifest.get("version") or "") != install.get("package_version"):
        raise HTTPException(409, "扩展版本不匹配")
    installed_owner = install.get("owner_scope")
    if installed_owner and installed_owner != owner:
        raise HTTPException(403, "当前账号无权使用此扩展安装")
    if manifest.get("scope") != "global":
        if installed_owner != owner:
            raise HTTPException(403, "定制扩展尚未绑定当前账号")
        entitlement = str(manifest.get("entitlement_mod_id") or mod_id)
        binding = load_session_private_delivery_binding(session_id_from_request(request))
        if not binding.get("market_user_id") or not {mod_id, entitlement}.intersection(
            binding.get("mod_ids", set())
        ):
            raise HTTPException(403, "当前账号未开通此定制扩展")
    return install, manifest, owner


def authorized_runtime(request: Request, mod_id: str) -> tuple[dict[str, Any], dict[str, Any], str]:
    install, manifest, owner = authorized_install(request, mod_id)
    backend = manifest.get("backend")
    if (
        isinstance(backend, dict)
        and backend.get("entry")
        and install.get("runtime_status") != "running"
    ):
        raise HTTPException(409, "扩展后端尚未就绪，请重启客户端后重试")
    frontend = manifest.get("frontend")
    runtime = frontend.get("runtime") if isinstance(frontend, dict) else None
    if not isinstance(runtime, dict) or runtime.get("sdk_version") != 1:
        raise HTTPException(409, "扩展前端 SDK 版本不受支持")
    return install, runtime, owner


def runtime_metadata(request: Request, mod_id: str) -> dict[str, Any]:
    install, runtime, owner = authorized_runtime(request, mod_id)
    entry = str(runtime.get("entry") or "")
    if not entry.startswith("frontend/runtime/") or PurePosixPath(entry).suffix != ".js":
        raise HTTPException(409, "扩展必须提供本地编译后的 JavaScript 入口")
    _verified_file(install, entry)
    routes = runtime.get("routes")
    if not isinstance(routes, list) or not 1 <= len(routes) <= 32:
        raise HTTPException(409, "扩展路由声明无效")
    prefix = f"/mod/{mod_id}"
    normalized = []
    for index, route in enumerate(routes):
        path = route.get("path") if isinstance(route, dict) else None
        if not isinstance(path, str) or not re.fullmatch(r"/[A-Za-z0-9/_-]+", path):
            raise HTTPException(409, "扩展路由无效")
        if path != prefix and not path.startswith(prefix + "/"):
            raise HTTPException(409, "扩展路由不能覆盖宿主或其他扩展")
        normalized.append(
            {
                "path": path,
                "name": f"runtime-{mod_id}-{index}",
                "title": str(route.get("title") or mod_id),
            }
        )
    revision = str(install["package_sha256"])
    return {
        "mod_id": mod_id,
        "package_version": install["package_version"],
        "package_sha256": revision,
        "owner_scope": owner,
        "sdk_version": 1,
        "entry_url": f"/api/mods/runtime/{mod_id}/assets/{revision}/{entry}",
        "routes": normalized,
        "requires_restart": bool(install.get("requires_restart")),
        "runtime_status": install.get("runtime_status", "installed"),
    }


def runtime_asset(
    request: Request, mod_id: str, revision: str, relative_path: str
) -> tuple[bytes, str]:
    install, _runtime, _owner = authorized_runtime(request, mod_id)
    if revision != install["package_sha256"]:
        raise HTTPException(409, "扩展版本已更新，请重新打开页面")
    suffix = PurePosixPath(relative_path).suffix
    if not relative_path.startswith("frontend/runtime/") or suffix not in _ASSET_TYPES:
        raise HTTPException(404, "扩展资源不可用")
    return _verified_file(install, relative_path), _ASSET_TYPES[suffix]


def visible_mod_rows(request: Request, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Do not leak private menus through process-global entitlement caches."""
    visible = []
    for row in rows:
        frontend = row.get("frontend")
        runtime = frontend.get("runtime") if isinstance(frontend, dict) else None
        if row.get("scope", "global") != "global" or runtime:
            try:
                authorized_install(request, str(row.get("id") or ""))
            except HTTPException:
                continue
        visible.append(row)
    return visible
