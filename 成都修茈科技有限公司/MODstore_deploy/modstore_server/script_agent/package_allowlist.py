"""第三方包审核 allowlist 加载器。

默认指向 ``MODstore_deploy/runtime_allowlist.json``。管理员审核通过的
包按下述结构写入::

    {
      "$schema_version": 1,
      "packages": {
        "openpyxl": {
          "version_spec": ">=3.1",
          "approved_by": "alice",
          "approved_at": "2026-04-28",
          "notes": "Excel 读写"
        }
      }
    }

读不到或解析失败时返回空 allowlist（脚本只能用 stdlib + ``modstore_runtime``），
而不是抛错，以免单个文件损坏阻断整个代理流程。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Optional, Set

DEFAULT_ALLOWLIST = Path(__file__).resolve().parent.parent.parent / "runtime_allowlist.json"


def load(path: Optional[Path] = None) -> Dict[str, Any]:
    p = path or DEFAULT_ALLOWLIST
    if not p.exists():
        return {"$schema_version": 1, "packages": {}}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return {"$schema_version": 1, "packages": {}}
        return data
    except Exception:  # noqa: BLE001
        return {"$schema_version": 1, "packages": {}}


def allowed_packages(path: Optional[Path] = None) -> Set[str]:
    data = load(path)
    pkgs = data.get("packages") or {}
    if not isinstance(pkgs, dict):
        return set()
    return {str(k) for k in pkgs.keys() if isinstance(k, str)}


def save(data: Dict[str, Any], path: Optional[Path] = None) -> None:
    """保存 allowlist 到磁盘（管理员审核流程使用）。"""
    p = path or DEFAULT_ALLOWLIST
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def upsert_package(
    name: str,
    *,
    version_spec: str = "",
    approved_by: str = "",
    notes: str = "",
    path: Optional[Path] = None,
) -> Dict[str, Any]:
    """添加 / 更新一个包的审核信息。"""
    from datetime import datetime, timezone

    if not name or not name.replace("_", "").replace("-", "").isalnum():
        raise ValueError(f"非法包名: {name!r}")
    data = load(path)
    pkgs = data.setdefault("packages", {})
    if not isinstance(pkgs, dict):
        pkgs = {}
        data["packages"] = pkgs
    pkgs[name] = {
        "version_spec": version_spec,
        "approved_by": approved_by,
        "approved_at": datetime.now(timezone.utc).isoformat(timespec="seconds") + "Z",
        "notes": notes,
    }
    save(data, path)
    return pkgs[name]


def remove_package(name: str, *, path: Optional[Path] = None) -> bool:
    """从 allowlist 移除包。返回是否真的移除了一行。"""
    data = load(path)
    pkgs = data.get("packages") or {}
    if not isinstance(pkgs, dict) or name not in pkgs:
        return False
    pkgs.pop(name, None)
    save(data, path)
    return True
