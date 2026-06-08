"""管理员维护「沙箱第三方包 allowlist」的 API。

端点：

- ``GET    /api/admin/runtime-allowlist`` —— 列出已审核包（任何登录用户可读，便于
  Composer 提示"可用三方包"）
- ``POST   /api/admin/runtime-allowlist`` —— 新增 / 更新一行（仅管理员）
- ``DELETE /api/admin/runtime-allowlist/{name}`` —— 移除一行（仅管理员）

实际写入路径：``MODstore_deploy/runtime_allowlist.json``，被
:mod:`modstore_server.script_agent.static_checker` 在校验时加载。
"""

from __future__ import annotations

from typing import Any, Dict, List

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from modstore_server.api.deps import _get_current_user, _require_admin
from modstore_server.models import User
from modstore_server.script_agent import package_allowlist

router = APIRouter(prefix="/api/admin/runtime-allowlist", tags=["runtime-allowlist"])


class UpsertPackageBody(BaseModel):
    name: str = Field(..., min_length=1, max_length=128)
    version_spec: str = Field("", max_length=128)
    notes: str = Field("", max_length=2000)


@router.get("", summary="列出脚本沙箱可用的第三方包（已审核 allowlist）")
async def list_packages(_: User = Depends(_get_current_user)) -> Dict[str, Any]:
    data = package_allowlist.load()
    pkgs = data.get("packages") or {}
    rows: List[Dict[str, Any]] = []
    for name, meta in pkgs.items():
        if not isinstance(meta, dict):
            continue
        rows.append(
            {
                "name": name,
                "version_spec": str(meta.get("version_spec") or ""),
                "approved_by": str(meta.get("approved_by") or ""),
                "approved_at": str(meta.get("approved_at") or ""),
                "notes": str(meta.get("notes") or ""),
            }
        )
    rows.sort(key=lambda r: r["name"])
    return {"packages": rows, "total": len(rows)}


@router.post("", summary="新增 / 更新审核包（管理员）")
async def upsert_package(
    body: UpsertPackageBody,
    user: User = Depends(_require_admin),
) -> Dict[str, Any]:
    try:
        meta = package_allowlist.upsert_package(
            body.name.strip(),
            version_spec=body.version_spec.strip(),
            approved_by=user.username,
            notes=body.notes.strip(),
        )
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    return {"name": body.name.strip(), **meta}


@router.delete("/{name}", summary="移除审核包（管理员）")
async def delete_package(
    name: str,
    _: User = Depends(_require_admin),
) -> Dict[str, Any]:
    removed = package_allowlist.remove_package(name)
    if not removed:
        raise HTTPException(404, f"allowlist 中不存在: {name}")
    return {"ok": True, "name": name}
