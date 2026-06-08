"""员工 workspace_policy（scope_globs / forbidden_globs）相对仓库根路径校验。"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional, Sequence

from modstore_server.integrations.doc_sync_handler import _match_glob
from modstore_server.integrations.ops_action_handlers import repo_root


def workspace_policy_from_manifest(manifest: Any) -> tuple[list[str], list[str], list[str]]:
    """从员工包 manifest 读取 ``employee_config_v2.workspace_policy``。

    返回 ``(scope_globs, forbidden_globs, approval_required_globs)``。
    """
    if not isinstance(manifest, dict):
        return [], [], []
    ev2 = manifest.get("employee_config_v2")
    if not isinstance(ev2, dict):
        return [], [], []
    wp = ev2.get("workspace_policy")
    if not isinstance(wp, dict):
        return [], [], []
    sg = [str(x).strip() for x in (wp.get("scope_globs") or []) if str(x).strip()]
    fg = [str(x).strip() for x in (wp.get("forbidden_globs") or []) if str(x).strip()]
    ag = [str(x).strip() for x in (wp.get("approval_required_globs") or []) if str(x).strip()]
    return sg, fg, ag


def relative_path_under_repo(resolved_file: Path) -> str:
    """返回相对仓库根的正斜杠路径；不在仓库内返回空串。"""
    root = repo_root().resolve()
    try:
        return str(Path(resolved_file).resolve().relative_to(root)).replace("\\", "/")
    except ValueError:
        return ""


def safe_resolve_under_directory(root: Path, fragment: str) -> tuple[Optional[Path], Optional[str]]:
    """将 ``fragment`` 解析为 ``root`` 下的绝对路径；禁止绝对路径与 ``..`` 穿越。"""
    raw = str(fragment or "").strip()
    if not raw:
        return None, "路径片段不能为空"
    if Path(raw).is_absolute() or raw.startswith(("/", "\\")):
        return None, f"禁止使用绝对路径: {fragment!r}"
    norm = raw.replace("\\", "/").strip("/")
    parts = [x for x in norm.split("/") if x and x != "."]
    if any(p == ".." for p in parts):
        return None, f"禁止路径穿越: {fragment!r}"
    base = root.resolve()
    try:
        candidate = base.joinpath(*parts).resolve() if parts else base
        candidate.relative_to(base)
    except ValueError:
        return None, f"路径越界（须在 root 之下）: {fragment!r}"
    return candidate, None


def validate_repo_paths_for_employee_pack(
    session: Any,
    employee_id: str,
    paths: Sequence[Path],
) -> Optional[str]:
    """对员工 manifest 的 ``workspace_policy`` 校验多个仓库内路径；无策略或无员工包则放行。"""
    from modstore_server.employee_runtime import load_employee_pack

    pid = str(employee_id or "").strip()
    if not pid or not paths:
        return None
    try:
        pack = load_employee_pack(session, pid)
    except ValueError:
        pack = {"manifest": {}}
    manifest = pack.get("manifest") if isinstance(pack.get("manifest"), dict) else {}
    sg, fg, _ag = workspace_policy_from_manifest(manifest)
    if not sg and not fg:
        return None
    for p in paths:
        rel = relative_path_under_repo(Path(p))
        if not rel:
            return (
                "路径不在仓库根之下，无法进行 scope 校验"
                "（请设置 MODSTORE_REPO_ROOT，或将路径置于仓库内）。"
            )
        ok_sc, msg_sc = validate_agent_repo_write(rel, sg, fg)
        if not ok_sc:
            return msg_sc
    return None


def validate_agent_repo_write(
    rel_repo_path: str,
    scope_globs: Sequence[str],
    forbidden_globs: Sequence[str],
) -> tuple[bool, str]:
    """相对仓库根的路径：先禁后白；若 ``scope_globs`` 为空则不做白名单限制（仍执行 forbidden）。"""
    rel = (rel_repo_path or "").replace("\\", "/").lstrip("/")
    fg = [str(x) for x in forbidden_globs if str(x).strip()]
    sg = [str(x) for x in scope_globs if str(x).strip()]
    if fg and _match_glob(rel, fg):
        return False, "路径匹配 forbidden_globs，拒绝写入"
    if sg and not _match_glob(rel, sg):
        return False, "路径不在 scope_globs 允许范围内"
    return True, ""
