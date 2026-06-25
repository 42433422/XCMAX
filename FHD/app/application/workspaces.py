"""工厂 Workspace 注册表：把超级员工(工厂版)派工的目标 repo 从裸 ``workspace_root``
字符串升成受平台控制的注册表。承接"先自举再外扩"：

- **P1 自举**：注册表只有 ``xcmax`` 一个 self workspace，``isolation=none`` →
  :meth:`WorkspaceRegistry.checkout` 直接返回工程根（与今天逐字节一致，零行为变化）。
- **P2 外扩**：在 ``config/workspaces.json`` 新增外部 repo 条目并改 ``isolation=worktree``
  → ``checkout`` 每任务 ``git worktree add`` 隔离，工厂引擎本身一行不改。
"""

from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

from app.mod_sdk.host_profile import resolve_fhd_config_dir

DEFAULT_WORKSPACE_ID = "xcmax"


class WorkspaceError(RuntimeError):
    """workspace 不存在 / 工作树缺失 / git 隔离失败。"""


def _xcmax_repo_root() -> Path:
    """含 FHD 的工程根（如 ``~/Desktop/XCMAX``）。

    与 ``super_employee_service._cli_workspace`` 的默认解析保持一致：让工厂派工覆盖整个
    工程而非仅 FHD 子目录。
    """
    env = str(
        os.environ.get("XCMAX_REPO_ROOT") or os.environ.get("MODSTORE_REPO_ROOT") or ""
    ).strip()
    if env and Path(env).exists():
        return Path(env)
    here = Path(__file__).resolve()
    for parent in here.parents:
        if parent.name == "FHD":
            return parent.parent
    return here.parents[3]


def _expand_root(raw: Any) -> Path:
    text = str(raw or "").strip()
    if not text or text == "${XCMAX_REPO_ROOT}":
        return _xcmax_repo_root()
    return Path(os.path.expandvars(os.path.expanduser(text)))


@dataclass(frozen=True)
class Workspace:
    id: str
    label: str
    root: Path
    vcs_kind: str = "git"
    default_branch: str = "main"
    isolation: str = "none"  # none | worktree


def _fallback_doc() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "workspaces": {
            DEFAULT_WORKSPACE_ID: {
                "id": DEFAULT_WORKSPACE_ID,
                "label": "XCMAX 主项目",
                "root": "${XCMAX_REPO_ROOT}",
                "isolation": "none",
                "self": True,
            }
        },
    }


@lru_cache(maxsize=1)
def _load_registry_doc() -> dict[str, Any]:
    cfg = resolve_fhd_config_dir()
    if cfg is not None:
        path = cfg / "workspaces.json"
        try:
            if path.is_file():
                doc = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(doc, dict) and isinstance(doc.get("workspaces"), dict):
                    return doc
        except (OSError, ValueError):
            pass
    return _fallback_doc()


class WorkspaceRegistry:
    """``config/workspaces.json`` 的只读视图 + 工作目录解析。"""

    def __init__(self, doc: dict[str, Any] | None = None) -> None:
        self._doc = doc if isinstance(doc, dict) else _load_registry_doc()

    def _entries(self) -> dict[str, Any]:
        ws = self._doc.get("workspaces")
        return ws if isinstance(ws, dict) else {}

    def get(self, workspace_id: str | None) -> Workspace:
        wid = str(workspace_id or DEFAULT_WORKSPACE_ID).strip() or DEFAULT_WORKSPACE_ID
        raw = self._entries().get(wid)
        if not isinstance(raw, dict):
            if wid == DEFAULT_WORKSPACE_ID:
                return Workspace(
                    id=DEFAULT_WORKSPACE_ID,
                    label="XCMAX 主项目",
                    root=_xcmax_repo_root(),
                    isolation="none",
                )
            raise WorkspaceError(f"unknown workspace: {wid}")
        vcs = raw.get("vcs") if isinstance(raw.get("vcs"), dict) else {}
        return Workspace(
            id=wid,
            label=str(raw.get("label") or wid),
            root=_expand_root(raw.get("root")),
            vcs_kind=str(vcs.get("kind") or "git"),
            default_branch=str(vcs.get("default_branch") or "main"),
            isolation=str(raw.get("isolation") or "none").strip().lower(),
        )

    def list(self) -> list[Workspace]:
        return [self.get(wid) for wid in self._entries()]

    def checkout(self, ws: Workspace, *, task_id: str) -> Path:
        """解析出本次派工的工作目录。

        - ``isolation=none``（P1 自举）：直接返回 ``ws.root``（与今天一致）。
        - ``isolation=worktree``（P2）：在工程根同级 ``.xcmax-worktrees/<id>-<task>``
          下 ``git worktree add --detach``，每任务一个隔离工作树，并行安全。
        """
        if not ws.root.exists():
            raise WorkspaceError(f"workspace root missing: {ws.root}")
        if ws.isolation != "worktree":
            return ws.root
        safe = (
            "".join(c for c in str(task_id or "task") if c.isalnum() or c in "._-")[:48] or "task"
        )
        worktree = ws.root.parent / ".xcmax-worktrees" / f"{ws.id}-{safe}"
        if worktree.exists():
            return worktree
        worktree.parent.mkdir(parents=True, exist_ok=True)
        try:
            subprocess.run(
                [
                    "git",
                    "-C",
                    str(ws.root),
                    "worktree",
                    "add",
                    "--detach",
                    str(worktree),
                    ws.default_branch,
                ],
                check=True,
                capture_output=True,
                text=True,
            )
        except (OSError, subprocess.CalledProcessError) as exc:  # pragma: no cover - 环境相关
            raise WorkspaceError(f"git worktree add failed: {exc}") from exc
        return worktree


def get_workspace_registry() -> WorkspaceRegistry:
    return WorkspaceRegistry()


__all__ = [
    "DEFAULT_WORKSPACE_ID",
    "Workspace",
    "WorkspaceError",
    "WorkspaceRegistry",
    "get_workspace_registry",
]
