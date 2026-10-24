"""Auto-merged part* modules (debt24)."""

from __future__ import annotations
import importlib
import os
import stat
from pathlib import Path
from modstore_server.employee_change_request_verification import (
    _guard_under_workspace,
    _workspace_fd,
)
from modstore_server.operational_errors import RECOVERABLE_ERRORS

# --- from mod_employee_agent_runner_part01.py ---
"""Implementation extracted from the public facade module."""


import importlib


def _facade():
    return importlib.import_module("modstore_server.mod_employee_agent_runner")


def _bounded_env_int(name: str, default: int, *, minimum: int, maximum: int) -> int:
    try:
        value = int(str(_facade().os.environ.get(name) or default).strip())
    except (TypeError, ValueError):
        value = default
    return max(minimum, min(maximum, value))


def _default_max_rounds() -> int:
    return _facade()._bounded_env_int(
        "MODSTORE_EMPLOYEE_AGENT_MAX_ROUNDS", 4, minimum=1, maximum=10
    )


def _llm_timeout_seconds() -> float:
    return float(
        _facade()._bounded_env_int(
            "MODSTORE_EMPLOYEE_AGENT_LLM_TIMEOUT_SECONDS", 45, minimum=10, maximum=120
        )
    )


# --- from mod_employee_agent_runner_part02.py ---
"""Implementation extracted from the public facade module."""


import importlib
import os
import stat
from pathlib import Path

from modstore_server.employee_change_request_verification import (
    _guard_under_workspace,
    _workspace_fd,
)
from modstore_server.operational_errors import RECOVERABLE_ERRORS


def _facade():
    return importlib.import_module("modstore_server.mod_employee_agent_runner")


def _guard_path(workspace_root: str, path: str) -> str | None:
    return _guard_under_workspace(workspace_root, path)


async def tool_read_workspace_file(
    workspace_root: str,
    path: str,
    ctx: _facade().Optional[_facade().Mapping[str, _facade().Any]] = None,
) -> _facade().Dict[str, _facade().Any]:
    ctx = ctx or {}
    rr = ctx.get("ops_readonly_repo_root")
    if rr:
        try:
            from modstore_server.integrations.ops_action_handlers import (
                ops_path_allowed,
            )

            root = _facade().Path(str(rr)).resolve()
            norm = path.replace("\\", "/").lstrip("./")
            if ops_path_allowed(norm):
                full = (root / norm).resolve()
                try:
                    full.relative_to(root)
                except ValueError:
                    return {"ok": False, "error": f"路径越界：{path!r}"}
                if _facade().os.path.isfile(full):
                    try:
                        with _workspace_fd(str(root), norm) as fd:
                            with os.fdopen(
                                os.dup(fd), "r", encoding="utf-8", errors="replace"
                            ) as stream:
                                content = stream.read()
                        truncated = len(content) > 8000
                        return {
                            "ok": True,
                            "path": path,
                            "content": content[:8000],
                            "truncated": truncated,
                            "total_chars": len(content),
                            "via": "ops_readonly_repo_root",
                        }
                    except OSError as exc:
                        return {"ok": False, "error": str(exc)[:300]}
        except RECOVERABLE_ERRORS as exc:
            return {"ok": False, "error": f"ops read failed: {exc}"[:300]}
    resolved = _facade()._guard_path(workspace_root, path)
    if resolved is None:
        return {"ok": False, "error": f"路径越界：{path!r}"}
    if not _facade().os.path.isfile(resolved):
        return {"ok": False, "error": f"文件不存在：{path!r}"}
    try:
        with _workspace_fd(workspace_root, path) as fd:
            with os.fdopen(os.dup(fd), "r", encoding="utf-8", errors="replace") as stream:
                content = stream.read()
        truncated = len(content) > 8000
        return {
            "ok": True,
            "path": path,
            "content": content[:8000],
            "truncated": truncated,
            "total_chars": len(content),
        }
    except OSError as exc:
        return {"ok": False, "error": str(exc)[:300]}


async def tool_write_workspace_file(
    workspace_root: str,
    path: str,
    content: str,
    ctx: _facade().Optional[_facade().Mapping[str, _facade().Any]] = None,
) -> _facade().Dict[str, _facade().Any]:
    ctx = ctx or {}
    if ctx.get("read_only"):
        return {"ok": False, "blocked": True, "error": "只读运行模式禁止写入"}
    resolved = _facade()._guard_path(workspace_root, path)
    if resolved is None:
        return {"ok": False, "error": f"路径越界：{path!r}"}
    sg = [str(x).strip() for x in ctx.get("scope_globs") or [] if str(x).strip()]
    fg = [str(x).strip() for x in ctx.get("forbidden_globs") or [] if str(x).strip()]
    ag = [str(x).strip() for x in ctx.get("approval_required_globs") or [] if str(x).strip()]
    if sg or fg:
        from modstore_server.employee_scope_policy import (
            relative_path_under_repo,
            validate_agent_repo_write,
        )

        rel_repo = relative_path_under_repo(_facade().Path(resolved))
        if not rel_repo:
            return {
                "ok": False,
                "error": "无法在仓库根下解析路径（scope 校验需要 MODSTORE_REPO_ROOT 与工作区位于仓库内）",
            }
        ok_sc, msg_sc = validate_agent_repo_write(rel_repo, sg, fg)
        if not ok_sc:
            try:
                from modstore_server.employee_autonomy_service import (
                    create_employee_suggestion,
                )

                create_employee_suggestion(
                    source_employee_id=str(ctx.get("employee_id") or "unknown"),
                    summary=f"路径越界/禁写建议：{path[:120]}",
                    detail=msg_sc[:1000],
                    payload={
                        "kind": "scope_violation",
                        "path": path[:500],
                        "detail": msg_sc[:500],
                        "target_employee_ids": ["daily-orchestrator"],
                    },
                    target_employee_ids=["daily-orchestrator"],
                    kind="scope_violation",
                    risk_level="medium",
                    emit_event=True,
                    auto_dispatch=True,
                )
            except RECOVERABLE_ERRORS:
                pass
            return {"ok": False, "error": msg_sc[:400]}
    emp_id = str(ctx.get("employee_id") or "").strip()
    bypass = bool(ctx.get("bypass_change_request"))
    if emp_id and (not bypass) and (emp_id != "daily-orchestrator"):
        try:
            from modstore_server.employee_change_request_service import (
                defer_write_as_change_request,
            )

            cid = defer_write_as_change_request(
                emp_id,
                workspace_root,
                path,
                content,
                scope_globs=sg,
                forbidden_globs=fg,
                approval_required_globs=ag,
            )
            return {
                "ok": True,
                "deferred": True,
                "change_request_id": cid,
                "path": path,
                "message": "变更已提交审批队列，批准后将写入文件",
            }
        except RECOVERABLE_ERRORS as exc:
            return {"ok": False, "error": str(exc)[:400]}
    try:
        with _workspace_fd(workspace_root, path, write=True) as fd:
            with os.fdopen(os.dup(fd), "w", encoding="utf-8") as stream:
                os.ftruncate(fd, 0)
                stream.write(content or "")
        return {
            "ok": True,
            "path": path,
            "bytes_written": len((content or "").encode("utf-8")),
        }
    except OSError as exc:
        return {"ok": False, "error": str(exc)[:300]}


async def tool_list_workspace_dir(
    workspace_root: str, path: str = "."
) -> _facade().Dict[str, _facade().Any]:
    resolved = _facade()._guard_path(workspace_root, path)
    if resolved is None:
        return {"ok": False, "error": f"路径越界：{path!r}"}
    if not _facade().os.path.isdir(resolved):
        return {"ok": False, "error": f"目录不存在：{path!r}"}
    try:
        entries = []
        with _workspace_fd(workspace_root, path, directory=True) as fd:
            for name in sorted(os.listdir(fd))[:50]:
                if name in {
                    ".git",
                    "node_modules",
                    "__pycache__",
                    ".venv",
                    "venv",
                    "dist",
                    "build",
                }:
                    continue
                info = os.stat(name, dir_fd=fd, follow_symlinks=False)
                if stat.S_ISLNK(info.st_mode):
                    continue
                is_dir = stat.S_ISDIR(info.st_mode)
                entries.append(
                    {
                        "name": name,
                        "type": "dir" if is_dir else "file",
                        "size": 0 if is_dir else info.st_size,
                    }
                )
        return {"ok": True, "path": path, "entries": entries, "count": len(entries)}
    except OSError as exc:
        return {"ok": False, "error": str(exc)[:300]}


async def tool_run_sandboxed_python(
    code: str, *, timeout: float = 10.0
) -> _facade().Dict[str, _facade().Any]:
    """Fail closed until a process/filesystem/network sandbox is available."""
    return {
        "ok": False,
        "blocked": True,
        "error": "Python execution requires an isolated sandbox",
    }


async def tool_scan_project_tree(
    workspace_root: str, path: str = ".", *, max_files: int = 200
) -> _facade().Dict[str, _facade().Any]:
    """Recursively scan *path* within *workspace_root*, returning a flat file list
    with type stats.  Skips common noise dirs (.git, node_modules, __pycache__, etc.)."""
    resolved = _facade()._guard_path(workspace_root, path)
    if resolved is None:
        return {"ok": False, "error": f"路径越界：{path!r}"}
    if not _facade().os.path.isdir(resolved):
        return {"ok": False, "error": f"目录不存在：{path!r}"}
    skip_dirs = {
        ".git",
        "node_modules",
        "__pycache__",
        ".venv",
        "venv",
        "dist",
        "build",
        ".mypy_cache",
    }
    entries: _facade().List[_facade().Dict[str, _facade().Any]] = []
    ext_count: _facade().Dict[str, int] = {}
    total = 0
    truncated = False
    try:
        with _workspace_fd(workspace_root, path, directory=True) as fd:
            for cur, dirs, files, current_fd in os.fwalk(".", dir_fd=fd, follow_symlinks=False):
                dirs[:] = sorted(
                    d
                    for d in dirs
                    if d not in skip_dirs
                    and not stat.S_ISLNK(
                        os.stat(d, dir_fd=current_fd, follow_symlinks=False).st_mode
                    )
                )
                for fname in sorted(files):
                    info = os.stat(fname, dir_fd=current_fd, follow_symlinks=False)
                    if not stat.S_ISREG(info.st_mode):
                        continue
                    if total >= max_files:
                        truncated = True
                        break
                    rel_path = os.path.join(cur, fname).removeprefix("./")
                    ext = os.path.splitext(fname)[1].lower() or "(no ext)"
                    entries.append({"path": rel_path, "ext": ext, "size": info.st_size})
                    ext_count[ext] = ext_count.get(ext, 0) + 1
                    total += 1
                if truncated:
                    break
    except OSError as exc:
        return {"ok": False, "error": str(exc)[:300]}
    return {
        "ok": True,
        "root": path,
        "total_files": total,
        "truncated": truncated,
        "max_files": max_files,
        "file_type_stats": dict(sorted(ext_count.items(), key=lambda x: -x[1])),
        "files": entries,
    }


async def tool_identify_file_types(
    workspace_root: str, path: str = "."
) -> _facade().Dict[str, _facade().Any]:
    result = await tool_scan_project_tree(workspace_root, path, max_files=2000)
    if not result.get("ok"):
        return result
    return {
        "ok": True,
        "path": path,
        "total_files_counted": result["total_files"],
        "file_types": result["file_type_stats"],
    }


async def tool_analyze_project_summary(
    workspace_root: str, path: str = "."
) -> _facade().Dict[str, _facade().Any]:
    listing = await tool_list_workspace_dir(workspace_root, path)
    if not listing.get("ok"):
        return listing
    manifests = {}
    readme_snippet = ""
    for name in (
        "package.json",
        "pyproject.toml",
        "setup.cfg",
        "Cargo.toml",
        "README.md",
        "README.rst",
        "README.txt",
        "readme.md",
    ):
        result = await tool_read_workspace_file(workspace_root, os.path.join(path, name))
        if result.get("ok"):
            if name.lower().startswith("readme"):
                if not readme_snippet:
                    readme_snippet = result["content"][:800]
            else:
                manifests[name] = result["content"][:3000]
    return {
        "ok": True,
        "path": path,
        "root_name": Path(workspace_root, path).name,
        "top_level": [entry["name"] for entry in listing["entries"]],
        "manifests": manifests,
        "readme_snippet": readme_snippet,
        "note": "workspace no-follow scan",
    }


# --- from mod_employee_agent_runner_part03.py ---
"""Implementation extracted from the public facade module."""


import importlib


def _facade():
    return importlib.import_module("modstore_server.mod_employee_agent_runner")


class EmployeeAgentRunner(_facade()._EmployeeAgentRunnerPart01Mixin):
    """ReAct agent loop for employee_pack employees.

    Usage in a generated employee file::

        async def run(payload, ctx):
            runner = ctx.get("agent_runner")  # injected by blueprints.py
            if runner is None:
                from modstore_server.mod_employee_agent_runner import EmployeeAgentRunner
                runner = EmployeeAgentRunner(ctx)
            task = payload.get("task") or payload.get("message") or json.dumps(payload)
            return await runner.run(task, system_prompt=SYSTEM_PROMPT)
    """


def _try_parse_json(
    text: str,
) -> _facade().Optional[_facade().Dict[str, _facade().Any]]:
    """Lenient JSON parser: strip fences and try multiple extract strategies."""
    t = (text or "").strip()
    t = (
        _facade()
        .re.sub("<think\\b[^>]*>.*?</think>", "", t, flags=_facade().re.I | _facade().re.S)
        .strip()
    )
    if t.startswith("```"):
        t = _facade().re.sub("^```(?:json)?\\s*", "", t, flags=_facade().re.I)
        t = _facade().re.sub("\\s*```\\s*$", "", t).strip()
    try:
        data = _facade().json.loads(t)
        return data if isinstance(data, dict) else None
    except (_facade().json.JSONDecodeError, ValueError):
        pass
    decoder = _facade().json.JSONDecoder()
    candidates: _facade().List[tuple[int, int, _facade().Dict[str, _facade().Any]]] = []
    for index, char in enumerate(t):
        if char != "{":
            continue
        try:
            data, _end = decoder.raw_decode(t[index:])
        except (_facade().json.JSONDecodeError, ValueError):
            continue
        if not isinstance(data, dict):
            continue
        score = 4 if "tool" in data else 4 if "answer" in data else 2 if "status" in data else 1
        candidates.append((score, index, data))
    if candidates:
        return max(candidates, key=lambda item: (item[0], item[1]))[2]
    return None


def build_agent_runner(
    ctx: _facade().Dict[str, _facade().Any],
    *,
    max_rounds: _facade().Optional[int] = None,
) -> EmployeeAgentRunner:
    """Convenience factory; used by generated blueprints.py."""
    workspace_root = str(ctx.get("workspace_root") or ".")
    return _facade().EmployeeAgentRunner(ctx, max_rounds=max_rounds, workspace_root=workspace_root)
