"""员工工作区持久化管理器。

为每个员工分配 MODSTORE_RUNTIME_DIR/workspaces/{employee_id}/ 持久工作区，
支持容量限制与过期清理（配合 file_retention_janitor.py）。

环境变量：
  MODSTORE_RUNTIME_DIR              — 运行时根目录（默认 /tmp/modstore_runtime）
  MODSTORE_WORKSPACE_MAX_MB         — 单员工工作区最大 MB（默认 200）
  MODSTORE_WORKSPACE_RETENTION_DAYS — 工作区文件最长保留天数（默认 30）
"""

from __future__ import annotations

import logging
import os
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


def _runtime_dir() -> Path:
    env = os.environ.get("MODSTORE_RUNTIME_DIR", "").strip()
    if env:
        return Path(env).resolve()
    return Path("/tmp/modstore_runtime")


def _max_mb() -> int:
    try:
        return int(os.environ.get("MODSTORE_WORKSPACE_MAX_MB", "200"))
    except ValueError:
        return 200


def _retention_days() -> int:
    try:
        return int(os.environ.get("MODSTORE_WORKSPACE_RETENTION_DAYS", "30"))
    except ValueError:
        return 30


def get_workspace_path(employee_id: str) -> Path:
    """返回员工工作区目录（已创建）。"""
    eid = (employee_id or "").strip().replace("/", "_").replace("\\", "_")
    if not eid:
        raise ValueError("employee_id must not be empty")
    ws = _runtime_dir() / "workspaces" / eid
    ws.mkdir(parents=True, exist_ok=True)
    return ws


def get_workspace_size_mb(employee_id: str) -> float:
    """返回员工工作区当前占用 MB。"""
    ws = get_workspace_path(employee_id)
    total = sum(f.stat().st_size for f in ws.rglob("*") if f.is_file())
    return total / (1024 * 1024)


def enforce_workspace_limit(employee_id: str) -> Dict[str, object]:
    """检查并执行容量限制：超限时删除最旧文件，直到低于阈值。

    返回 {"before_mb": float, "after_mb": float, "deleted_files": int}
    """
    max_mb = _max_mb()
    ws = get_workspace_path(employee_id)
    before_mb = get_workspace_size_mb(employee_id)
    deleted = 0

    if before_mb <= max_mb:
        return {"before_mb": before_mb, "after_mb": before_mb, "deleted_files": 0}

    # 按 mtime 升序（最旧的先删）
    files = sorted(
        [f for f in ws.rglob("*") if f.is_file()],
        key=lambda f: f.stat().st_mtime,
    )
    for f in files:
        if get_workspace_size_mb(employee_id) <= max_mb:
            break
        try:
            f.unlink()
            deleted += 1
        except Exception:
            pass

    after_mb = get_workspace_size_mb(employee_id)
    logger.info(
        "workspace_manager: enforce_limit employee=%s before=%.1fMB after=%.1fMB deleted=%d",
        employee_id,
        before_mb,
        after_mb,
        deleted,
    )
    return {"before_mb": before_mb, "after_mb": after_mb, "deleted_files": deleted}


def cleanup_expired_workspaces() -> Dict[str, object]:
    """清理所有员工工作区中超过 retention_days 的文件。

    配合 file_retention_janitor.py 调用。
    """
    ws_root = _runtime_dir() / "workspaces"
    if not ws_root.exists():
        return {"cleaned_files": 0, "employees": []}

    cutoff = datetime.now(timezone.utc) - timedelta(days=_retention_days())
    cleaned = 0
    employees_cleaned: List[str] = []

    for emp_dir in ws_root.iterdir():
        if not emp_dir.is_dir():
            continue
        emp_files_cleaned = 0
        for f in emp_dir.rglob("*"):
            if not f.is_file():
                continue
            try:
                mtime = datetime.utcfromtimestamp(f.stat().st_mtime)
                if mtime < cutoff:
                    f.unlink()
                    emp_files_cleaned += 1
                    cleaned += 1
            except Exception:
                pass
        if emp_files_cleaned > 0:
            employees_cleaned.append(emp_dir.name)

    logger.info(
        "workspace_manager: cleanup expired: %d files from %d employees",
        cleaned,
        len(employees_cleaned),
    )
    return {"cleaned_files": cleaned, "employees": employees_cleaned}


def list_workspaces() -> List[Dict[str, object]]:
    """列出所有员工工作区状态。"""
    ws_root = _runtime_dir() / "workspaces"
    if not ws_root.exists():
        return []
    result = []
    for emp_dir in sorted(ws_root.iterdir()):
        if not emp_dir.is_dir():
            continue
        size_bytes = sum(f.stat().st_size for f in emp_dir.rglob("*") if f.is_file())
        files = sum(1 for f in emp_dir.rglob("*") if f.is_file())
        result.append(
            {
                "employee_id": emp_dir.name,
                "path": str(emp_dir),
                "size_mb": round(size_bytes / (1024 * 1024), 2),
                "files": files,
            }
        )
    return result


__all__ = [
    "get_workspace_path",
    "get_workspace_size_mb",
    "enforce_workspace_limit",
    "cleanup_expired_workspaces",
    "list_workspaces",
]
