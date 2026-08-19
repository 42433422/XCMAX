# ruff: noqa
"""Implementation extracted from the public facade module."""
from __future__ import annotations
import importlib


def _facade():
    return importlib.import_module("modstore_server.mod_employee_agent_runner")


def _guard_path(workspace_root: str, path: str) -> _facade().Optional[str]:
    """Return resolved absolute path only if it stays inside workspace_root."""
    resolved = _facade().os.path.normpath(_facade().os.path.join(workspace_root, path))
    workspace_abs = _facade().os.path.abspath(workspace_root)
    if not resolved.startswith(workspace_abs + _facade().os.sep) and resolved != workspace_abs:
        return None
    return resolved


async def tool_read_workspace_file(
    workspace_root: str,
    path: str,
    ctx: _facade().Optional[_facade().Mapping[str, _facade().Any]] = None,
) -> _facade().Dict[str, _facade().Any]:
    ctx = ctx or {}
    rr = ctx.get("ops_readonly_repo_root")
    if rr:
        try:
            from modstore_server.integrations.ops_action_handlers import ops_path_allowed

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
                        content = _facade().Path(full).read_text(encoding="utf-8", errors="replace")
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
        except Exception as exc:
            return {"ok": False, "error": f"ops read failed: {exc}"[:300]}
    resolved = _facade()._guard_path(workspace_root, path)
    if resolved is None:
        return {"ok": False, "error": f"路径越界：{path!r}"}
    if not _facade().os.path.isfile(resolved):
        return {"ok": False, "error": f"文件不存在：{path!r}"}
    try:
        content = _facade().Path(resolved).read_text(encoding="utf-8", errors="replace")
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
        (ok_sc, msg_sc) = validate_agent_repo_write(rel_repo, sg, fg)
        if not ok_sc:
            try:
                from modstore_server.employee_autonomy_service import create_employee_suggestion

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
            except Exception:
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
        except Exception as exc:
            return {"ok": False, "error": str(exc)[:400]}
    try:
        _facade().os.makedirs(_facade().os.path.dirname(resolved) or ".", exist_ok=True)
        _facade().Path(resolved).write_text(content or "", encoding="utf-8")
        return {"ok": True, "path": path, "bytes_written": len((content or "").encode("utf-8"))}
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
        skip = {".git", "node_modules", "__pycache__", ".venv", "venv", "dist", "build"}
        entries = []
        for name in sorted(_facade().os.listdir(resolved))[:50]:
            if name in skip:
                continue
            full = _facade().os.path.join(resolved, name)
            is_dir = _facade().os.path.isdir(full)
            entries.append(
                {
                    "name": name,
                    "type": "dir" if is_dir else "file",
                    "size": 0 if is_dir else _facade().os.path.getsize(full),
                }
            )
        return {"ok": True, "path": path, "entries": entries, "count": len(entries)}
    except OSError as exc:
        return {"ok": False, "error": str(exc)[:300]}


async def tool_run_sandboxed_python(
    code: str, *, timeout: float = 10.0
) -> _facade().Dict[str, _facade().Any]:
    """Run pure-stdlib Python in a subprocess with a hard time limit."""
    danger = _facade().re.compile(
        "\\b(import\\s+subprocess|import\\s+socket|import\\s+urllib|open\\s*\\(|__import__|exec\\s*\\(|eval\\s*\\(|compile\\s*\\(|os\\.system|shutil\\.rmtree)\\b"
    )
    if danger.search(code):
        return {"ok": False, "error": "代码包含不允许的操作（网络/文件/exec/eval）"}
    try:
        proc = _facade().subprocess.run(
            [_facade().sys.executable, "-c", code],
            capture_output=True,
            text=True,
            timeout=timeout,
            env={
                k: v
                for (k, v) in _facade().os.environ.items()
                if k in ("PATH", "PYTHONPATH", "TEMP", "TMP")
            },
        )
        return {
            "ok": proc.returncode == 0,
            "stdout": proc.stdout[:2000],
            "stderr": proc.stderr[:500],
            "returncode": proc.returncode,
        }
    except _facade().subprocess.TimeoutExpired:
        return {"ok": False, "error": f"执行超时（{timeout:.0f}s）"}
    except FileNotFoundError:
        return {"ok": False, "error": "Python 运行时不可用"}
    except Exception as exc:
        return {"ok": False, "error": str(exc)[:300]}


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
    for cur, dirs, files in _facade().os.walk(resolved):
        dirs[:] = sorted((d for d in dirs if d not in skip_dirs))
        rel_cur = _facade().os.path.relpath(cur, resolved).replace("\\", "/")
        rel_cur = "" if rel_cur == "." else rel_cur
        for fname in sorted(files):
            if total >= max_files:
                truncated = True
                break
            rel_path = f"{rel_cur}/{fname}".lstrip("/")
            ext = _facade().os.path.splitext(fname)[1].lower() or "(no ext)"
            size = 0
            try:
                size = _facade().os.path.getsize(_facade().os.path.join(cur, fname))
            except OSError:
                pass
            entries.append({"path": rel_path, "ext": ext, "size": size})
            ext_count[ext] = ext_count.get(ext, 0) + 1
            total += 1
        if truncated:
            break
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
    """Count file extensions under *path* within *workspace_root* (non-recursive limit 2000)."""
    resolved = _facade()._guard_path(workspace_root, path)
    if resolved is None:
        return {"ok": False, "error": f"路径越界：{path!r}"}
    if not _facade().os.path.isdir(resolved):
        return {"ok": False, "error": f"目录不存在：{path!r}"}
    skip_dirs = {".git", "node_modules", "__pycache__", ".venv", "venv", "dist", "build"}
    ext_count: _facade().Dict[str, int] = {}
    total = 0
    for cur, dirs, files in _facade().os.walk(resolved):
        dirs[:] = [d for d in dirs if d not in skip_dirs]
        for fname in files:
            if total >= 2000:
                break
            ext = _facade().os.path.splitext(fname)[1].lower() or "(no ext)"
            ext_count[ext] = ext_count.get(ext, 0) + 1
            total += 1
    return {
        "ok": True,
        "path": path,
        "total_files_counted": total,
        "file_types": dict(sorted(ext_count.items(), key=lambda x: -x[1])),
    }


async def tool_analyze_project_summary(
    workspace_root: str, path: str = "."
) -> _facade().Dict[str, _facade().Any]:
    """Return a structured project summary using vibe-coding's analyze_project if available,
    otherwise fall back to a lightweight manual scan."""
    resolved = _facade()._guard_path(workspace_root, path)
    if resolved is None:
        return {"ok": False, "error": f"路径越界：{path!r}"}
    if not _facade().os.path.isdir(resolved):
        return {"ok": False, "error": f"目录不存在：{path!r}"}
    try:
        from vibe_coding.code_factory import analyze_project

        analysis = analyze_project(resolved)
        return {
            "ok": True,
            "path": path,
            "root_name": analysis.root_name,
            "top_level": analysis.top_level,
            "languages": analysis.languages,
            "tech_stack": analysis.tech_stack,
            "entry_points": analysis.entry_points,
            "config_files": analysis.config_files,
            "readme_snippet": analysis.readme_snippet,
            "manifests": analysis.manifests,
            "git_info": analysis.git_info,
        }
    except ImportError:
        pass
    except Exception as exc:
        _facade().logger.warning("analyze_project failed, falling back: %s", exc)
    top_level = sorted(_facade().os.listdir(resolved))[:40]
    manifests: _facade().Dict[str, _facade().Any] = {}
    readme_snippet = ""
    for mf in ("package.json", "pyproject.toml", "setup.cfg", "Cargo.toml"):
        mp = _facade().os.path.join(resolved, mf)
        if _facade().os.path.isfile(mp):
            try:
                content = _facade().Path(mp).read_text(encoding="utf-8", errors="replace")[:3000]
                manifests[mf] = content
            except OSError:
                pass
    for rf in ("README.md", "README.rst", "README.txt", "readme.md"):
        rp = _facade().os.path.join(resolved, rf)
        if _facade().os.path.isfile(rp):
            try:
                readme_snippet = (
                    _facade().Path(rp).read_text(encoding="utf-8", errors="replace")[:800]
                )
            except OSError:
                pass
            break
    return {
        "ok": True,
        "path": path,
        "root_name": _facade().os.path.basename(resolved),
        "top_level": top_level,
        "manifests": manifests,
        "readme_snippet": readme_snippet,
        "note": "vibe-coding 未安装，使用轻量级扫描",
    }
