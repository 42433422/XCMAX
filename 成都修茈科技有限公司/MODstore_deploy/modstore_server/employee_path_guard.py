"""员工路径边界硬约束（10 项成熟度要求第 2 项 — 知道自己管什么）。

soft 约束：system_prompt 写"只操作 X" — LLM 可能不听。
hard 约束（本模块）：actions 执行后检查 changed_files 是否在 scope_globs 内、
                   是否命中 forbidden_globs，越权则 block。

挂载点：employee_executor.execute_employee_task → _actions_real 之后。
"""

from __future__ import annotations

import fnmatch
from typing import Any, Dict, List


def _normalize_repo_path(p: str) -> str:
    """统一为 repo 相对路径（去掉前缀 ./ 和绝对路径前缀）。"""
    s = str(p or "").strip().replace("\\", "/")
    # 去掉 ./ 前缀
    while s.startswith("./"):
        s = s[2:]
    # 去掉绝对路径前缀（保留 repo 相对部分）
    if s.startswith("/"):
        s = s.lstrip("/")
    return s


def _extract_changed_files_from_output(out: Any) -> List[str]:
    """从单个 handler output 抽取它声明改/写/创建的文件路径。

    兼容多种字段命名：files_changed / changed_files / file_path / path /
    created_files / modified_files / output_path。

    特别处理 llm_md / echo 类 handler：它们的 output 字段是 LLM 输出 JSON 字符串，
    里面可能含 files_changed 字段（LLM 想"改"的文件）。这里也尝试解析。
    """
    if not isinstance(out, dict):
        return []
    paths: List[str] = []
    # 列表型字段
    for key in (
        "files_changed",
        "changed_files",
        "created_files",
        "modified_files",
        "touched_files",
    ):
        v = out.get(key)
        if isinstance(v, list):
            for item in v:
                if isinstance(item, str):
                    paths.append(item)
                elif isinstance(item, dict):
                    p = str(item.get("path") or item.get("file") or "").strip()
                    if p:
                        paths.append(p)
    # 字典型字段（单个路径）
    for key in ("file_path", "path", "output_path", "file"):
        v = out.get(key)
        if isinstance(v, str) and v.strip():
            paths.append(v)
    # 特殊处理：output 字段是 LLM 输出 JSON 字符串，里面可能含 files_changed
    output_field = out.get("output")
    if isinstance(output_field, str) and output_field.strip().startswith("{"):
        import json as _json

        try:
            parsed = _json.loads(output_field)
            if isinstance(parsed, dict):
                # 递归一次（不深递归，避免性能问题）
                for key in (
                    "files_changed",
                    "changed_files",
                    "created_files",
                    "modified_files",
                    "touched_files",
                ):
                    v = parsed.get(key)
                    if isinstance(v, list):
                        for item in v:
                            if isinstance(item, str):
                                paths.append(item)
                            elif isinstance(item, dict):
                                p = str(item.get("path") or item.get("file") or "").strip()
                                if p:
                                    paths.append(p)
                for key in ("file_path", "path", "output_path", "file"):
                    v = parsed.get(key)
                    if isinstance(v, str) and v.strip():
                        paths.append(v)
        except (ValueError, TypeError):
            pass
    return paths


def _matches_any(path: str, globs: List[str]) -> bool:
    """检查路径是否匹配任一 glob（fnmatch，** 等价于 * 跨目录）。"""
    if not globs:
        return False
    norm = _normalize_repo_path(path)
    for g in globs:
        g = str(g or "").strip()
        if not g:
            continue
        # ** 跨目录，fnmatch 不原生支持，等价于 * 多段
        if "**" in g:
            # 把 ** 拆成 * 多段
            pattern = g.replace("**/", "*").replace("/**", "/*").replace("**", "*")
        else:
            pattern = g
        if fnmatch.fnmatch(norm, pattern):
            return True
        # 也匹配前缀（如 yuangon/ 匹配 yuangon/anything）
        if norm.startswith(pattern.rstrip("*").rstrip("/")):
            return True
    return False


def check_path_guard(
    *,
    config: Dict[str, Any],
    result: Dict[str, Any],
    employee_id: str,
) -> Dict[str, Any]:
    """检查 actions 结果里 changed_files 是否在 scope 内、不命中 forbidden。

    返回：
      {
        "ok": bool,                  # True 表示通过，False 表示有越权
        "checked": bool,             # 是否进行了检查（scope/forbidden 都为空时 False）
        "scope_globs": [...],
        "forbidden_globs": [...],
        "violations": [{             # 越权路径列表
            "path": "src/main.py",
            "reason": "out_of_scope" | "matches_forbidden",
            "matched_glob": "*.py",  # 命中 forbidden 时填
            "handler": "agent",
        }],
        "all_changed_files": [...],  # 全部检测到的 changed 文件（用于审计）
      }
    """
    wp = config.get("workspace_policy") if isinstance(config, dict) else None
    if not isinstance(wp, dict):
        wp = {}
    scope_globs = [str(x) for x in (wp.get("scope_globs") or []) if str(x).strip()]
    forbidden_globs = [str(x) for x in (wp.get("forbidden_globs") or []) if str(x).strip()]

    # 没配边界 → 不检查（避免误伤没配 scope 的员工）
    if not scope_globs and not forbidden_globs:
        return {
            "ok": True,
            "checked": False,
            "scope_globs": [],
            "forbidden_globs": [],
            "violations": [],
            "all_changed_files": [],
            "note": "未配置 workspace_policy.scope_globs / forbidden_globs，跳过 path guard",
        }

    # 抽取所有 handler 声明改/写的文件
    outputs = result.get("outputs") if isinstance(result, dict) else []
    if not isinstance(outputs, list):
        outputs = []
    all_files: List[str] = []
    file_to_handler: Dict[str, str] = {}
    for out in outputs:
        if not isinstance(out, dict):
            continue
        handler_name = str(out.get("handler") or "")
        files = _extract_changed_files_from_output(out)
        for f in files:
            all_files.append(f)
            file_to_handler[f] = handler_name

    violations: List[Dict[str, Any]] = []
    for path in all_files:
        norm = _normalize_repo_path(path)
        if not norm:
            continue
        # 先检查 forbidden（高优先级）
        for g in forbidden_globs:
            g = str(g).strip()
            if not g:
                continue
            pattern = (
                g.replace("**/", "*").replace("/**", "/*").replace("**", "*") if "**" in g else g
            )
            if fnmatch.fnmatch(norm, pattern):
                violations.append(
                    {
                        "path": norm,
                        "reason": "matches_forbidden",
                        "matched_glob": g,
                        "handler": file_to_handler.get(path, ""),
                    }
                )
                break
        else:
            # 不在 forbidden → 检查 scope
            if scope_globs and not _matches_any(norm, scope_globs):
                violations.append(
                    {
                        "path": norm,
                        "reason": "out_of_scope",
                        "matched_glob": "",
                        "handler": file_to_handler.get(path, ""),
                    }
                )

    return {
        "ok": len(violations) == 0,
        "checked": True,
        "scope_globs": scope_globs,
        "forbidden_globs": forbidden_globs,
        "violations": violations,
        "all_changed_files": all_files,
    }


__all__ = ["check_path_guard"]
