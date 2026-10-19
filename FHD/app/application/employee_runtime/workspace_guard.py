"""工作空间策略的运行时强制（WorkspaceGuard）。

此前 ``scope_globs`` / ``forbidden_globs`` 只在 ``scripts/dev/verify_employee_contract.py``
做静态校验，运行时完全不生效。本模块把它变成对每次 tool_call 的运行时 gate：

- ``forbidden_globs``：对所有触碰文件的路径强制（安全红线，例如密钥/支付/迁移）。
- ``scope_globs``：对「写类」工具与「输出路径」参数强制（避免误读上传文件被错杀）。
- ``read_only`` 员工：直接拒绝写库类工具。

gate 签名与 ``agent_loop.GateFn`` 一致：``(tool_name, args) -> {"ok": bool, "reason": str}``。
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any, cast

from app.application.employee_runtime.tool_scope import CODE_WRITE_TOOLS, WRITE_TOOLS, is_read_only

logger = logging.getLogger(__name__)

# 触碰文件的参数键
_INPUT_PATH_KEYS = ("file_path", "path", "filepath", "input_path", "src", "source")
_OUTPUT_PATH_KEYS = (
    "output_path",
    "out_path",
    "dest",
    "destination",
    "save_path",
    "output",
    "target",
)
_LIST_PATH_KEYS = ("file_paths", "paths", "files", "inputs", "targets")

# 输出类工具：scope_globs 对其强制（含代码修改工具）
_WRITE_LIKE_TOOLS = WRITE_TOOLS | {"generate_office_document"} | CODE_WRITE_TOOLS


def _glob_to_regex(pattern: str) -> str:
    pat = str(pattern or "").strip()
    i, n = 0, len(pat)
    out = ["^"]
    while i < n:
        c = pat[i]
        if c == "*":
            if i + 1 < n and pat[i + 1] == "*":
                i += 2
                if i < n and pat[i] == "/":
                    out.append("(?:.*/)?")
                    i += 1
                else:
                    out.append(".*")
            else:
                out.append("[^/]*")
                i += 1
        elif c == "?":
            out.append("[^/]")
            i += 1
        else:
            out.append(re.escape(c))
            i += 1
    out.append("$")
    return "".join(out)


def _compile_globs(globs: list[str]) -> list[tuple[re.Pattern[str], bool]]:
    """返回 [(regex, has_slash)]。gitignore 语义：不含 `/` 的 glob 匹配任意层级 basename。"""
    compiled: list[tuple[re.Pattern[str], bool]] = []
    for g in globs or []:
        gs = str(g).strip()
        if not gs:
            continue
        try:
            compiled.append((re.compile(_glob_to_regex(gs)), "/" in gs))
        except re.error:
            logger.debug("invalid workspace glob skipped", exc_info=True)
    return compiled


def _matches_any(rel_path: str, patterns: list[tuple[re.Pattern[str], bool]]) -> bool:
    base = rel_path.rsplit("/", 1)[-1]
    for regex, has_slash in patterns:
        target = rel_path if has_slash else base
        if regex.match(target):
            return True
    return False


def _workspace_policy(manifest: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    wp = (
        config.get("workspace_policy") if isinstance(config.get("workspace_policy"), dict) else None
    )
    if wp:
        return cast("dict[str, Any]", wp)
    v2 = (
        manifest.get("employee_config_v2")
        if isinstance(manifest.get("employee_config_v2"), dict)
        else {}
    )
    if not isinstance(v2, dict):
        v2 = {}
    wp2 = v2.get("workspace_policy") if isinstance(v2.get("workspace_policy"), dict) else {}
    return wp2 or {}


def _resolve_in_workspace(path: str, workspace_root: str | None) -> tuple[str, bool]:
    """返回 ``(规范化相对路径, 是否仍在工作区内)``。

    先 ``resolve()`` 跟随符号链接再 ``relative_to(root)``，因此指向工作区外的
    符号链接、``..`` 穿越与绝对路径都会被判定为越界；判断与后续工具使用的是
    同一个真实路径语义，避免「检查用字符串、执行时再解链接」的替换窗口。
    """
    raw = str(path or "").strip()
    if not raw:
        return "", True
    p = Path(raw)
    if not workspace_root:
        return p.as_posix().lstrip("./"), True
    try:
        root = Path(workspace_root).resolve()
        cand = (p if p.is_absolute() else root / p).resolve()
        return cand.relative_to(root).as_posix(), True
    except (ValueError, OSError):
        # 不在 workspace 内：返回原路径，由调用方按 inside=False 拒绝
        return p.as_posix(), False


def _normalize_rel(path: str, workspace_root: str | None) -> str:
    rel, _inside = _resolve_in_workspace(path, workspace_root)
    return rel


def _extract_paths(args: dict[str, Any]) -> list[tuple[str, bool]]:
    """返回 [(path, is_output)]。"""
    out: list[tuple[str, bool]] = []
    if not isinstance(args, dict):
        return out
    for k in _INPUT_PATH_KEYS:
        v = args.get(k)
        if isinstance(v, str) and v.strip():
            out.append((v, False))
    for k in _OUTPUT_PATH_KEYS:
        v = args.get(k)
        if isinstance(v, str) and v.strip():
            out.append((v, True))
    for k in _LIST_PATH_KEYS:
        v = args.get(k)
        if isinstance(v, list):
            for item in v:
                if isinstance(item, str) and item.strip():
                    out.append((item, False))
    return out


def build_employee_gate(
    employee_id: str,
    manifest: dict[str, Any],
    config: dict[str, Any],
    workspace_root: str | None,
):
    """构造员工工作空间 gate；无可强制项时返回 None（零开销）。"""
    wp = _workspace_policy(manifest, config)
    scope = _compile_globs(wp.get("scope_globs") or [])
    forbidden = _compile_globs(wp.get("forbidden_globs") or [])
    read_only = is_read_only(manifest, config)

    if not scope and not forbidden and not read_only:
        return None

    def gate(tool_name: str, args: dict[str, Any]) -> dict[str, Any]:
        name = str(tool_name or "").strip()
        if read_only and name in WRITE_TOOLS:
            return {"ok": False, "reason": f"员工 {employee_id} 为只读，禁止写库工具 {name}"}

        enforce_scope = bool(scope) and name in _WRITE_LIKE_TOOLS
        for raw_path, is_output in _extract_paths(args):
            rel, inside = _resolve_in_workspace(raw_path, workspace_root)
            if not rel:
                continue
            if not inside:
                return {
                    "ok": False,
                    "reason": (
                        f"路径 {raw_path} 解析后位于工作区之外"
                        "（符号链接或目录替换越界），已拒绝"
                    ),
                }
            if forbidden and _matches_any(rel, forbidden):
                return {"ok": False, "reason": f"路径 {raw_path} 命中 forbidden_globs（禁止访问）"}
            if (enforce_scope or is_output) and scope and not _matches_any(rel, scope):
                return {
                    "ok": False,
                    "reason": f"写入路径 {raw_path} 不在 scope_globs 允许范围内",
                }
        return {"ok": True}

    return gate


__all__ = ["build_employee_gate"]
