"""Run delivered employees inside an authenticated, signed Mod installation."""

from __future__ import annotations

import inspect
import re
import uuid
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse

from app.mod_sdk.owner_workspace import owner_context, owner_workspace
from app.mod_sdk.runtime_frontend import authorized_install


def _runtime(request: Request, mod_id: str):
    install, manifest, owner = authorized_install(request, mod_id)
    if install.get("runtime_status") != "running":
        raise HTTPException(409, "员工扩展后端尚未就绪")
    config = manifest.get("private_employee_runtime")
    if not isinstance(config, dict) or config.get("sdk_version") != 1:
        raise HTTPException(409, "员工扩展运行合同无效")
    return install, config, owner


def _module(install: dict[str, Any], mod_id: str, stem: str):
    from app.mod_sdk.mods_bus import import_mod_backend_py

    if not re.fullmatch(r"[A-Za-z_]\w*(?:/[A-Za-z_]\w*)*", stem):
        raise HTTPException(409, "员工实现入口无效")
    module = import_mod_backend_py(install["installed_root"], mod_id, stem)
    if module is None:
        raise HTTPException(409, "员工实现尚未加载")
    return module


async def run_employee(request: Request, mod_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Use the original run handler; caller-supplied identity never selects its owner."""
    from app.application.employee_runtime.executor import _build_enriched_ctx
    from app.infrastructure.auth.dependencies import get_logged_in_user, session_id_from_request

    install, config, owner = _runtime(request, mod_id)
    workspace = owner_workspace(mod_id, owner_id=owner)
    workspace.root.mkdir(parents=True, exist_ok=True)
    data = dict(payload)
    for field in ("owner", "owner_id", "user_id", "session_id", "workspace_root"):
        data.pop(field, None)
    for field in ("file_path", "path", "output_path"):
        value = str(data.get(field) or "").strip()
        if not value:
            continue
        candidate = Path(value)
        candidate = candidate if candidate.is_absolute() else workspace.root / candidate
        resolved = candidate.resolve()
        if not resolved.is_relative_to(workspace.root.resolve()) or candidate.is_symlink():
            raise HTTPException(403, "员工文件必须属于当前账号工作区")
        data[field] = str(resolved)
    data["workspace_root"] = str(workspace.root)
    module = _module(install, mod_id, str(config.get("run_module") or ""))
    handler = getattr(module, "run", None)
    if not callable(handler):
        raise HTTPException(409, "员工未提供实际 run(payload, ctx) 实现")
    ctx = _build_enriched_ctx(str(config["employee_id"]), str(workspace.root))
    ctx.update(
        mod_id=mod_id,
        owner_id=owner,
        user_id=int(get_logged_in_user(request).id),
        request=request,
        session_id=session_id_from_request(request),
    )
    with owner_context(owner):
        result = handler(data, ctx)
        if inspect.isawaitable(result):
            result = await result
    if not isinstance(result, dict):
        raise HTTPException(409, "员工未返回可验证业务结果")
    files: list[str] = []

    def collect(value: Any) -> None:
        if isinstance(value, dict):
            for key, item in value.items():
                if key.endswith("path") and isinstance(item, str):
                    path = Path(item)
                    path = path if path.is_absolute() else workspace.root / path
                    if (
                        path.resolve().is_relative_to(workspace.root.resolve())
                        and path.is_file()
                        and not path.is_symlink()
                    ):
                        relative = path.resolve().relative_to(workspace.root.resolve()).as_posix()
                        if relative not in files:
                            files.append(relative)
                collect(item)
        elif isinstance(value, list):
            for item in value:
                collect(item)

    collect(result)
    return {
        "success": result.get("ok", result.get("success")) is True,
        "data": result,
        "files": files,
    }


async def verify_employee_delivery(request: Request, mod_id: str) -> dict[str, Any]:
    """Delegate to the source's real business probe without registering global employees."""
    install, config, owner = _runtime(request, mod_id)
    source = _module(install, mod_id, str(config.get("probe_module") or ""))
    probe = getattr(source, "verify_delivery", None)
    if not callable(probe):
        raise HTTPException(409, "员工交付缺少实际业务验证探针")
    with owner_context(owner):
        result = probe(request)
        if inspect.isawaitable(result):
            result = await result
    if not isinstance(result, dict):
        raise HTTPException(409, "员工业务探针未返回结果")
    return result


def register_private_employee_routes(app, mod_id: str) -> None:
    router = APIRouter(prefix=f"/api/mod/{mod_id}/employee")

    @router.post("/run")
    async def run(request: Request, payload: dict[str, Any]) -> dict[str, Any]:
        return await run_employee(request, mod_id, payload)

    @router.post("/input")
    async def upload(request: Request, file: UploadFile) -> dict[str, Any]:
        _install, _config, owner = _runtime(request, mod_id)
        workspace = owner_workspace(mod_id, owner_id=owner)
        workspace.root.mkdir(parents=True, exist_ok=True)
        suffix = Path(file.filename or "input").suffix[:16]
        name = "input-" + uuid.uuid4().hex + suffix
        content = await file.read(10 * 1024 * 1024 + 1)
        if len(content) > 10 * 1024 * 1024:
            raise HTTPException(413, "员工输入文件不能超过 10 MB")
        workspace.file_path(name).write_bytes(content)
        return {"success": True, "file_path": name}

    @router.get("/files")
    async def download(request: Request, path: str):
        _install, _config, owner = _runtime(request, mod_id)
        workspace = owner_workspace(mod_id, owner_id=owner)
        try:
            file = workspace.existing_file(path)
        except (OSError, ValueError):
            raise HTTPException(404, "当前账号文件不存在") from None
        return FileResponse(file, filename=file.name)

    app.include_router(router)
