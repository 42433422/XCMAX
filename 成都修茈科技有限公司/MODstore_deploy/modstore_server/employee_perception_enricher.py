"""员工感知增强（10 项成熟度第 1 项「看得见」）。

让员工在 cognition 阶段能看到自己负责的代码、最近执行、失败记录，
而不是只看到一句 task 文本就乱跑。

输入：employee_id + perceived（_perception_real 输出）+ config（含 workspace_policy）+ session
输出：在 perceived.normalized_input 里追加：
  - _workspace_signals: 自己负责的代码（scope_globs 下最近修改的 N 个文件）
  - _recent_runs: 最近 N 次执行摘要（成功/失败/耗时/tokens）
  - _recent_failures: 最近 N 次失败任务的失败原因
  - _scope_summary: 自己管什么（scope_globs / forbidden_globs 列表）
"""
from __future__ import annotations

import fnmatch
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

_MAX_FILES_SIGNAL = 15  # 最多给 LLM 看 15 个最近修改文件，避免 context 爆炸
_MAX_RECENT_RUNS = 5
_MAX_RECENT_FAILURES = 3
_MAX_FILE_SIZE_BYTES = 50_000  # 单文件大于 50KB 不读内容（只看路径+时间）


def _glob_to_python_pattern(glob: str) -> str:
    """把 ant 风格 glob 转 fnmatch 兼容 pattern。

    `**` 跨目录时降级为 `*`（fnmatch 原生不支持 `**`）。
    """
    g = str(glob or "").strip()
    if not g:
        return ""
    if "**" in g:
        g = g.replace("**/", "*").replace("/**", "/*").replace("**", "*")
    return g


def _scan_scope_files(
    project_root: Path,
    scope_globs: List[str],
    *,
    limit: int = _MAX_FILES_SIGNAL,
) -> List[Dict[str, Any]]:
    """扫描 project_root 下匹配 scope_globs 的文件，按修改时间倒序返回前 N 个。"""
    if not scope_globs or not project_root or not project_root.exists():
        return []
    seen: set[str] = set()
    candidates: List[Dict[str, Any]] = []
    for raw_glob in scope_globs:
        py_pattern = _glob_to_python_pattern(raw_glob)
        if not py_pattern:
            continue
        try:
            for p in project_root.rglob("*"):
                if not p.is_file():
                    continue
                rel = p.relative_to(project_root).as_posix()
                if rel in seen:
                    continue
                # 跳过常见噪音目录
                if any(seg in {"node_modules", ".venv", ".git", "__pycache__", "dist", "build"} for seg in p.parts):
                    continue
                if not fnmatch.fnmatch(rel, py_pattern):
                    continue
                seen.add(rel)
                try:
                    st = p.stat()
                    candidates.append({
                        "path": rel,
                        "size_bytes": int(st.st_size),
                        "mtime_iso": datetime.fromtimestamp(st.st_mtime, tz=timezone.utc).isoformat(),
                        "mtime_age_hours": round((datetime.now(timezone.utc).timestamp() - st.st_mtime) / 3600.0, 1),
                    })
                except OSError:
                    continue
        except (OSError, PermissionError):
            continue
    candidates.sort(key=lambda x: x.get("mtime_age_hours", 999999))
    return candidates[:limit]


def _recent_runs_from_db(
    session,
    employee_id: str,
    *,
    limit: int = _MAX_RECENT_RUNS,
) -> List[Dict[str, Any]]:
    """从 EmployeeExecutionMetric 表查最近 N 次执行摘要。"""
    try:
        from modstore_server.models_user import EmployeeExecutionMetric
    except ImportError:
        return []
    try:
        rows = (
            session.query(EmployeeExecutionMetric)
            .filter(EmployeeExecutionMetric.employee_id == employee_id)
            .order_by(EmployeeExecutionMetric.id.desc())
            .limit(limit)
            .all()
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug("recent_runs query failed employee_id=%s err=%s", employee_id, exc)
        return []
    out: List[Dict[str, Any]] = []
    for r in rows:
        out.append({
            "task": (r.task or "")[:120],
            "status": str(r.status or ""),
            "duration_ms": int(r.duration_ms or 0),
            "llm_tokens": int(r.llm_tokens or 0),
            "failure_kind": str(r.failure_kind or ""),
            "error_preview": (r.error_preview or "")[:200] if hasattr(r, "error_preview") else "",
            "created_at": r.created_at.isoformat() if r.created_at else None,
        })
    return out


def _recent_failures_from_db(
    session,
    employee_id: str,
    *,
    limit: int = _MAX_RECENT_FAILURES,
) -> List[Dict[str, Any]]:
    """从 EmployeeExecutionMetric 表查最近 N 次失败任务（含失败原因）。"""
    try:
        from modstore_server.models_user import EmployeeExecutionMetric
    except ImportError:
        return []
    try:
        rows = (
            session.query(EmployeeExecutionMetric)
            .filter(EmployeeExecutionMetric.employee_id == employee_id)
            .filter(EmployeeExecutionMetric.status.notin_(["success", "completed"]))
            .order_by(EmployeeExecutionMetric.id.desc())
            .limit(limit)
            .all()
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug("recent_failures query failed employee_id=%s err=%s", employee_id, exc)
        return []
    out: List[Dict[str, Any]] = []
    for r in rows:
        out.append({
            "task": (r.task or "")[:120],
            "status": str(r.status or ""),
            "failure_kind": str(r.failure_kind or ""),
            "error_preview": (r.error_preview or "")[:300] if hasattr(r, "error_preview") else "",
            "created_at": r.created_at.isoformat() if r.created_at else None,
        })
    return out


def enrich_perception(
    *,
    employee_id: str,
    perceived: Dict[str, Any],
    config: Dict[str, Any],
    session,
    project_root: Optional[Path] = None,
    manifest: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """把 workspace_signals / recent_runs / recent_failures 注入 perceived.normalized_input。

    返回的 perceived 是同一个 dict（原地修改 + 返回引用），不破坏原有字段。
    """
    if not isinstance(perceived, dict):
        return perceived
    ni = perceived.get("normalized_input")
    if not isinstance(ni, dict):
        ni = {}
        perceived["normalized_input"] = ni

    # workspace_policy: scope_globs / forbidden_globs
    # 优先从 config["workspace_policy"] 取（10 项成熟度第 2 项已统一放这里）；
    # 没有时回退到 manifest（employee_scope_policy.workspace_policy_from_manifest）。
    wp = config.get("workspace_policy") if isinstance(config, dict) else None
    if not isinstance(wp, dict):
        wp = {}
    scope_globs = [str(x) for x in (wp.get("scope_globs") or []) if str(x).strip()]
    forbidden_globs = [str(x) for x in (wp.get("forbidden_globs") or []) if str(x).strip()]
    if not scope_globs and not forbidden_globs and manifest:
        try:
            from modstore_server.employee_scope_policy import workspace_policy_from_manifest
            _sg, _fg, _ag = workspace_policy_from_manifest(manifest)
            scope_globs = _sg or []
            forbidden_globs = _fg or []
        except Exception as exc:  # noqa: BLE001
            logger.debug("workspace_policy_from_manifest failed employee_id=%s err=%s", employee_id, exc)

    ni["_scope_summary"] = {
        "scope_globs": scope_globs,
        "forbidden_globs": forbidden_globs,
        "note": "你负责的代码路径范围（scope_globs）和禁止触碰的路径（forbidden_globs）",
    }

    # 扫描自己负责的代码文件
    if scope_globs and project_root:
        try:
            files = _scan_scope_files(Path(project_root), scope_globs, limit=_MAX_FILES_SIGNAL)
            ni["_workspace_signals"] = {
                "files_recent_modified": files,
                "scope_root": str(project_root),
                "note": f"你负责的代码（scope_globs 匹配）最近修改的 {len(files)} 个文件",
            }
        except Exception as exc:  # noqa: BLE001
            ni["_workspace_signals"] = {"error": str(exc)[:200]}
    else:
        ni["_workspace_signals"] = {"note": "未配置 scope_globs 或 project_root，无法扫描代码文件"}

    # 最近执行摘要（成功/失败都要）
    try:
        runs = _recent_runs_from_db(session, employee_id, limit=_MAX_RECENT_RUNS)
        ni["_recent_runs"] = {
            "runs": runs,
            "note": f"你最近 {len(runs)} 次执行记录（含成功/失败）",
        }
    except Exception as exc:  # noqa: BLE001
        ni["_recent_runs"] = {"error": str(exc)[:200]}

    # 最近失败（重点看失败原因）
    try:
        failures = _recent_failures_from_db(session, employee_id, limit=_MAX_RECENT_FAILURES)
        ni["_recent_failures"] = {
            "failures": failures,
            "note": f"你最近 {len(failures)} 次失败任务的失败原因（如果有的话）",
        }
    except Exception as exc:  # noqa: BLE001
        ni["_recent_failures"] = {"error": str(exc)[:200]}

    return perceived


__all__ = ["enrich_perception"]
