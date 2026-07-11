"""ReAct agent loop + tool infrastructure for employee_pack.

This module provides the execution backbone that turns a single-shot employee
into a real agent able to read/write files, execute code and browse the web —
in the same way Cursor or other coding agents work: Reason → Act → Observe →
repeat until the task is done or the round limit is reached.

Architecture
------------

    ┌──────────────────────────────────────────────────────────┐
    │  blueprints.py  (generated per employee_pack)             │
    │  • builds ctx: call_llm, workspace tools, agent_runner   │
    │  • calls module.run(payload, ctx)                        │
    └────────────────┬─────────────────────────────────────────┘
                     │  ctx["agent_runner"]
                     ▼
    ┌──────────────────────────────────────────────────────────┐
    │  EmployeeAgentRunner.run(task, system_prompt)            │
    │  ┌──────────────────────────────────────────────────┐   │
    │  │  for round in range(max_rounds):                 │   │
    │  │    LLM → JSON(thought + tool/answer)             │   │
    │  │    if answer   → return                          │   │
    │  │    if tool     → dispatch → observe              │   │
    │  └──────────────────────────────────────────────────┘   │
    └──────────────────────────────────────────────────────────┘

Tool calling protocol (the LLM must respond with valid JSON every turn):

  Tool call (not yet done):
    { "thought": "why I need this tool",
      "tool": "tool_name",
      "input": { ...tool params... } }

  Final answer (task complete):
    { "thought": "summary",
      "answer": "the actual result or written content" }

Available tools (injected via ctx by blueprints.py):
    read_workspace_file(path)          — read a file relative to workspace_root
    write_workspace_file(path,content) — write / create a file
    list_workspace_dir(path=".")       — list directory entries
    run_sandboxed_python(code)         — run Python in subprocess (std-lib only, 10 s limit)
    http_get(url, headers)             — HTTP GET (from existing ctx)
    http_post(url, json_body)          — HTTP POST (from existing ctx)
    call_llm(messages)                 — nested LLM call for sub-tasks
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import os
import re
import subprocess
import uuid
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional

from modstore_server.management_work_operations import ManagementOperationConflict

logger = logging.getLogger(__name__)

# ── Protocol constants ────────────────────────────────────────────────────────

TOOL_PROTOCOL_HEADER = """你是一个能执行真实工作的 AI 员工。
每轮必须输出以下两种格式之一的 **合法 JSON**（不加 markdown 围栏，不加解释文字）：

调用工具（任务未完成时）：
{{
  "thought": "当前分析与下一步计划（至少 20 字）",
  "tool": "工具名",
  "input": {{ 工具所需参数 }}
}}

给出最终答案（任务已完成时）：
{{
  "thought": "总结本次执行路径",
  "answer": "完整的最终结果（可以是 Markdown / JSON / 纯文本）"
}}

可用工具（按需选用，每次只调用一个）：
  analyze_project_summary  params: path(str, default=".")                        — 【优先使用】读取并摘要项目结构（manifests/技术栈/入口文件/README前800字）
  scan_project_tree        params: path(str, default="."), max_files(int, 200)   — 递归扫描目录树，返回文件列表与类型统计
  identify_file_types      params: path(str, default=".")                        — 按扩展名统计目录中的文件类型分布
  read_workspace_file      params: path(str)                                     — 读取工作区文件，最多返回 8000 字符
  write_workspace_file     params: path(str), content(str)                       — 写入（创建或覆盖）文件
  list_workspace_dir       params: path(str, default=".")                        — 列出目录条目（最多 50 项）
  run_sandboxed_python     params: code(str)                                     — 在隔离子进程中运行纯 Python（标准库）
  http_get                 params: url(str), headers(dict)                       — 发起 HTTP GET
  http_post                params: url(str), json_body(dict)                     — 发起 HTTP POST

约束：
1. 每轮只调用一个工具；结果会以 {{"tool_result": {{...}}}} 回传。
2. 最多 {max_rounds} 轮工具调用后必须输出 answer。
3. 禁止捏造工具结果；必须等待真实返回后再继续。
4. 若工具返回 ok=false，分析原因并换一种思路或直接告知用户。
5. 文件路径必须是相对工作区的相对路径，禁止绝对路径和 ".." 越界。
6. 项目分析任务必须先调用 analyze_project_summary，再按需读取具体文件，不得无依据生成技术描述。
"""

RESEARCH_TOOLS_APPEND = """
  internet_search          params: query(str), max_results(int, 可选默认 8)             — 联网检索摘要（受服务器每日配额限制）
  github_repo_snapshot     params: owner(str), repo(str)                               — GitHub 公开仓库元数据与 README 摘录
"""

# ── Tool implementations ──────────────────────────────────────────────────────


def _guard_path(workspace_root: str, path: str) -> Optional[str]:
    """Return resolved absolute path only if it stays inside workspace_root."""
    resolved = os.path.normpath(os.path.join(workspace_root, path))
    workspace_abs = os.path.abspath(workspace_root)
    if not resolved.startswith(workspace_abs + os.sep) and resolved != workspace_abs:
        return None
    return resolved


async def tool_read_workspace_file(
    workspace_root: str,
    path: str,
    ctx: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    ctx = ctx or {}
    rr = ctx.get("ops_readonly_repo_root")
    if rr:
        try:
            from modstore_server.integrations.ops_action_handlers import ops_path_allowed

            root = Path(str(rr)).resolve()
            norm = path.replace("\\", "/").lstrip("./")
            if ops_path_allowed(norm):
                full = (root / norm).resolve()
                try:
                    full.relative_to(root)
                except ValueError:
                    return {"ok": False, "error": f"路径越界：{path!r}"}
                if os.path.isfile(full):
                    try:
                        content = Path(full).read_text(encoding="utf-8", errors="replace")
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
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": f"ops read failed: {exc}"[:300]}

    resolved = _guard_path(workspace_root, path)
    if resolved is None:
        return {"ok": False, "error": f"路径越界：{path!r}"}
    if not os.path.isfile(resolved):
        return {"ok": False, "error": f"文件不存在：{path!r}"}
    try:
        content = Path(resolved).read_text(encoding="utf-8", errors="replace")
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
    ctx: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    ctx = ctx or {}
    resolved = _guard_path(workspace_root, path)
    if resolved is None:
        return {"ok": False, "error": f"路径越界：{path!r}"}

    sg = [str(x).strip() for x in (ctx.get("scope_globs") or []) if str(x).strip()]
    fg = [str(x).strip() for x in (ctx.get("forbidden_globs") or []) if str(x).strip()]
    ag = [str(x).strip() for x in (ctx.get("approval_required_globs") or []) if str(x).strip()]
    management_context = (
        ctx.get("management_work_operation_context")
        if isinstance(ctx.get("management_work_operation_context"), dict)
        else {}
    )
    if sg or fg:
        from modstore_server.employee_scope_policy import (
            relative_path_under_repo,
            validate_agent_repo_write,
        )

        if management_context:
            try:
                rel_repo = str(
                    Path(resolved).resolve().relative_to(Path(workspace_root).resolve())
                ).replace("\\", "/")
            except ValueError:
                rel_repo = ""
        else:
            rel_repo = relative_path_under_repo(Path(resolved))
        if not rel_repo:
            return {
                "ok": False,
                "error": "无法在仓库根下解析路径（scope 校验需要 MODSTORE_REPO_ROOT 与工作区位于仓库内）",
            }
        ok_sc, msg_sc = validate_agent_repo_write(rel_repo, sg, fg)
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
    will_defer = bool(emp_id and not bypass and emp_id != "daily-orchestrator")
    operation_context = management_context
    operation: Dict[str, Any] | None = None
    operation_attempt = 0
    operation_nonce = ""
    compensation: Dict[str, Any] = {}
    content_sha256 = hashlib.sha256((content or "").encode("utf-8")).hexdigest()
    if operation_context.get("task_id"):
        from modstore_server.management_work_operations import (
            begin_operation,
            capture_file_compensation,
        )

        if not will_defer:
            compensation = capture_file_compensation(Path(resolved))
            compensation["expected_after_sha256"] = content_sha256
        reserved = begin_operation(
            task_id=str(operation_context.get("task_id") or ""),
            employee_id=emp_id,
            task_revision=int(operation_context.get("task_revision") or 1),
            logical_step=str(
                ctx.get("management_operation_step") or "write_workspace_file"
            ),
            kind="change_request.submit" if will_defer else "file.write",
            target=str(Path(resolved).resolve()),
            request={
                "relative_path": path,
                "content_sha256": content_sha256,
                "bytes": len((content or "").encode("utf-8")),
            },
            reversible=bool(compensation.get("reversible")) if not will_defer else False,
            compensation=compensation,
            safe_retry=not will_defer,
            execution_attempt=(
                int(operation_context.get("attempt"))
                if operation_context.get("attempt") is not None
                else None
            ),
        )
        operation = reserved.get("operation") if isinstance(reserved.get("operation"), dict) else {}
        operation_attempt = int(
            reserved.get("execution_attempt") or operation.get("attempt") or 0
        )
        operation_nonce = str(reserved.get("execution_nonce") or "")
        if reserved.get("action") == "replay":
            replay = reserved.get("result") if isinstance(reserved.get("result"), dict) else {}
            if (
                operation.get("kind") == "change_request.submit"
                and str(operation.get("external_ref") or "").startswith("change_request:")
            ):
                try:
                    replay_change_id = int(
                        str(operation["external_ref"]).split(":", 1)[1]
                    )
                except (TypeError, ValueError, IndexError):
                    replay_change_id = 0
                if replay_change_id > 0:
                    replay = {
                        **replay,
                        "management_evidence_claims": [
                            {
                                "claim_id": f"change_request_{replay_change_id}",
                                "kind": "change_request",
                                "change_request_id": replay_change_id,
                            }
                        ],
                    }
            return {
                **replay,
                "ok": replay.get("ok", True),
                "replayed": True,
                "management_operation": operation,
            }
        if reserved.get("action") != "execute":
            return {
                "ok": False,
                "error": str(reserved.get("reason") or "副作用结果未知，禁止自动重放")[:400],
                "management_operation": operation,
            }
    # 每日编排员写工作区日志/摘要，走直写；其余员工统一进 CR 审批链。
    if will_defer:
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
                management_operation_id=str(
                    (operation or {}).get("operation_id") or ""
                ),
                execution_attempt=operation_attempt,
                execution_nonce=operation_nonce,
            )
            return {
                "ok": True,
                "deferred": True,
                "change_request_id": cid,
                "path": path,
                "message": "变更已提交审批队列，批准后将写入文件",
                "management_operation": operation,
                "management_evidence_claims": [
                    {
                        "claim_id": f"change_request_{cid}",
                        "kind": "change_request",
                        "change_request_id": cid,
                    }
                ],
            }
        except Exception as exc:
            if operation:
                from modstore_server.management_work_operations import fail_operation

                try:
                    fail_operation(
                        str(operation.get("operation_id") or ""),
                        execution_attempt=operation_attempt,
                        execution_nonce=operation_nonce,
                        error=str(exc),
                        outcome_known_no_effect=True,
                    )
                except ManagementOperationConflict:
                    # Cancellation or a replacement lease already owns the
                    # operation. Preserve the original CR rejection and leave
                    # recovery to the authoritative management-work state.
                    pass
            return {"ok": False, "error": str(exc)[:400]}

    try:
        os.makedirs(os.path.dirname(resolved) or ".", exist_ok=True)
        destination = Path(resolved)
        current_exists = destination.exists()
        current_is_file = destination.is_file()
        current_sha256 = (
            hashlib.sha256(destination.read_bytes()).hexdigest()
            if current_is_file
            else ""
        )
        if operation:
            from modstore_server.management_work_operations import (
                assert_operation_execution_current,
                fail_operation,
            )

            assert_operation_execution_current(
                str(operation.get("operation_id") or ""),
                execution_attempt=operation_attempt,
                execution_nonce=operation_nonce,
            )
            registered = (
                operation.get("compensation")
                if isinstance(operation.get("compensation"), dict)
                else compensation
            )
            before_exists = registered.get("before_exists") is True
            before_sha256 = str(registered.get("before_sha256") or "")
            preimage_matches = (
                (not before_exists and not current_exists)
                or (
                    before_exists
                    and current_is_file
                    and bool(before_sha256)
                    and hmac.compare_digest(current_sha256, before_sha256)
                )
            )
            if not preimage_matches:
                failed = fail_operation(
                    str(operation.get("operation_id") or ""),
                    execution_attempt=operation_attempt,
                    execution_nonce=operation_nonce,
                    error="file preimage changed before write; refusing to overwrite concurrent update",
                    outcome_known_no_effect=True,
                )
                return {
                    "ok": False,
                    "error": "文件在写入前已被其他执行修改，已拒绝覆盖",
                    "management_operation": failed,
                }
        if current_sha256 != content_sha256:
            temporary = destination.with_name(
                f".{destination.name}.xcagi-write-{uuid.uuid4().hex}"
            )
            try:
                temporary.write_text(content or "", encoding="utf-8")
                if operation:
                    # Recheck both the task lease and the file preimage as close
                    # as possible to the atomic replace.  A stale worker or a
                    # concurrent writer must never be allowed to overwrite the
                    # newer state it did not observe.
                    assert_operation_execution_current(
                        str(operation.get("operation_id") or ""),
                        execution_attempt=operation_attempt,
                        execution_nonce=operation_nonce,
                    )
                    latest_exists = destination.exists()
                    latest_is_file = destination.is_file()
                    latest_sha256 = (
                        hashlib.sha256(destination.read_bytes()).hexdigest()
                        if latest_is_file
                        else ""
                    )
                    latest_matches = (
                        (not before_exists and not latest_exists)
                        or (
                            before_exists
                            and latest_is_file
                            and bool(before_sha256)
                            and hmac.compare_digest(latest_sha256, before_sha256)
                        )
                    )
                    if not latest_matches:
                        failed = fail_operation(
                            str(operation.get("operation_id") or ""),
                            execution_attempt=operation_attempt,
                            execution_nonce=operation_nonce,
                            error=(
                                "file preimage changed immediately before atomic replace; "
                                "refusing to overwrite concurrent update"
                            ),
                            outcome_known_no_effect=True,
                        )
                        return {
                            "ok": False,
                            "error": "文件在原子替换前发生并发修改，已拒绝覆盖",
                            "management_operation": failed,
                        }
                os.replace(temporary, destination)
            finally:
                try:
                    if temporary.exists():
                        temporary.unlink()
                except OSError:
                    pass
        result = {
            "ok": True,
            "path": path,
            "bytes_written": len((content or "").encode("utf-8")),
            "sha256": content_sha256,
            "management_evidence_claims": [
                {
                    "claim_id": f"file_{hashlib.sha256(path.encode('utf-8')).hexdigest()[:16]}",
                    "kind": "file",
                    "workspace_root": workspace_root,
                    "path": path,
                    "expected": {
                        "exists": True,
                        "min_size": len((content or "").encode("utf-8")),
                        "sha256": content_sha256,
                    },
                }
            ],
        }
        if operation:
            from modstore_server.management_work_operations import complete_operation

            compensation_record = dict(
                operation.get("compensation")
                if isinstance(operation.get("compensation"), dict)
                else compensation
            )
            compensation_record["after_sha256"] = content_sha256
            operation = complete_operation(
                str(operation.get("operation_id") or ""),
                execution_attempt=operation_attempt,
                execution_nonce=operation_nonce,
                result=result,
                external_ref=str(destination.resolve()),
                compensation=compensation_record,
            )
            result["management_operation"] = operation
        return result
    except OSError as exc:
        if operation:
            from modstore_server.management_work_operations import fail_operation

            fail_operation(
                str(operation.get("operation_id") or ""),
                execution_attempt=operation_attempt,
                execution_nonce=operation_nonce,
                error=str(exc),
                outcome_known_no_effect=True,
            )
        return {"ok": False, "error": str(exc)[:300]}
    except ManagementOperationConflict as exc:
        # The file may already have reached its postimage while cancellation
        # won the lease race.  Leave the operation running so recovery marks it
        # uncertain/reconciles it; never claim a known-no-effect failure here.
        return {
            "ok": False,
            "error": str(exc)[:300],
            "management_operation": operation or {},
        }


async def tool_list_workspace_dir(workspace_root: str, path: str = ".") -> Dict[str, Any]:
    resolved = _guard_path(workspace_root, path)
    if resolved is None:
        return {"ok": False, "error": f"路径越界：{path!r}"}
    if not os.path.isdir(resolved):
        return {"ok": False, "error": f"目录不存在：{path!r}"}
    try:
        skip = {".git", "node_modules", "__pycache__", ".venv", "venv", "dist", "build"}
        entries = []
        for name in sorted(os.listdir(resolved))[:50]:
            if name in skip:
                continue
            full = os.path.join(resolved, name)
            is_dir = os.path.isdir(full)
            entries.append(
                {
                    "name": name,
                    "type": "dir" if is_dir else "file",
                    "size": 0 if is_dir else os.path.getsize(full),
                }
            )
        return {"ok": True, "path": path, "entries": entries, "count": len(entries)}
    except OSError as exc:
        return {"ok": False, "error": str(exc)[:300]}


async def tool_run_sandboxed_python(code: str, *, timeout: float = 10.0) -> Dict[str, Any]:
    """Run pure-stdlib Python in a subprocess with a hard time limit."""
    # Block dangerous patterns before even launching a process.
    danger = re.compile(
        r"\b(import\s+subprocess|import\s+socket|import\s+urllib|open\s*\(|"
        r"__import__|exec\s*\(|eval\s*\(|compile\s*\(|os\.system|shutil\.rmtree)\b"
    )
    if danger.search(code):
        return {"ok": False, "error": "代码包含不允许的操作（网络/文件/exec/eval）"}
    try:
        proc = subprocess.run(
            ["python", "-c", code],
            capture_output=True,
            text=True,
            timeout=timeout,
            env={k: v for k, v in os.environ.items() if k in ("PATH", "PYTHONPATH", "TEMP", "TMP")},
        )
        return {
            "ok": proc.returncode == 0,
            "stdout": proc.stdout[:2000],
            "stderr": proc.stderr[:500],
            "returncode": proc.returncode,
        }
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": f"执行超时（{timeout:.0f}s）"}
    except FileNotFoundError:
        return {"ok": False, "error": "python 不在 PATH 中"}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc)[:300]}


async def tool_scan_project_tree(
    workspace_root: str,
    path: str = ".",
    *,
    max_files: int = 200,
) -> Dict[str, Any]:
    """Recursively scan *path* within *workspace_root*, returning a flat file list
    with type stats.  Skips common noise dirs (.git, node_modules, __pycache__, etc.)."""
    resolved = _guard_path(workspace_root, path)
    if resolved is None:
        return {"ok": False, "error": f"路径越界：{path!r}"}
    if not os.path.isdir(resolved):
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
    entries: List[Dict[str, Any]] = []
    ext_count: Dict[str, int] = {}
    total = 0
    truncated = False
    for cur, dirs, files in os.walk(resolved):
        dirs[:] = sorted(d for d in dirs if d not in skip_dirs)
        rel_cur = os.path.relpath(cur, resolved).replace("\\", "/")
        rel_cur = "" if rel_cur == "." else rel_cur
        for fname in sorted(files):
            if total >= max_files:
                truncated = True
                break
            rel_path = f"{rel_cur}/{fname}".lstrip("/")
            ext = os.path.splitext(fname)[1].lower() or "(no ext)"
            size = 0
            try:
                size = os.path.getsize(os.path.join(cur, fname))
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


async def tool_identify_file_types(workspace_root: str, path: str = ".") -> Dict[str, Any]:
    """Count file extensions under *path* within *workspace_root* (non-recursive limit 2000)."""
    resolved = _guard_path(workspace_root, path)
    if resolved is None:
        return {"ok": False, "error": f"路径越界：{path!r}"}
    if not os.path.isdir(resolved):
        return {"ok": False, "error": f"目录不存在：{path!r}"}
    skip_dirs = {".git", "node_modules", "__pycache__", ".venv", "venv", "dist", "build"}
    ext_count: Dict[str, int] = {}
    total = 0
    for cur, dirs, files in os.walk(resolved):
        dirs[:] = [d for d in dirs if d not in skip_dirs]
        for fname in files:
            if total >= 2000:
                break
            ext = os.path.splitext(fname)[1].lower() or "(no ext)"
            ext_count[ext] = ext_count.get(ext, 0) + 1
            total += 1
    return {
        "ok": True,
        "path": path,
        "total_files_counted": total,
        "file_types": dict(sorted(ext_count.items(), key=lambda x: -x[1])),
    }


async def tool_analyze_project_summary(workspace_root: str, path: str = ".") -> Dict[str, Any]:
    """Return a structured project summary using vibe-coding's analyze_project if available,
    otherwise fall back to a lightweight manual scan."""
    resolved = _guard_path(workspace_root, path)
    if resolved is None:
        return {"ok": False, "error": f"路径越界：{path!r}"}
    if not os.path.isdir(resolved):
        return {"ok": False, "error": f"目录不存在：{path!r}"}

    try:
        from vibe_coding.code_factory import analyze_project  # type: ignore[import-not-found]

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
    except Exception as exc:  # noqa: BLE001
        logger.warning("analyze_project failed, falling back: %s", exc)

    # Lightweight fallback: top-level listing + manifest reads + README snippet.
    top_level = sorted(os.listdir(resolved))[:40]
    manifests: Dict[str, Any] = {}
    readme_snippet = ""
    for mf in ("package.json", "pyproject.toml", "setup.cfg", "Cargo.toml"):
        mp = os.path.join(resolved, mf)
        if os.path.isfile(mp):
            try:
                content = Path(mp).read_text(encoding="utf-8", errors="replace")[:3000]
                manifests[mf] = content
            except OSError:
                pass
    for rf in ("README.md", "README.rst", "README.txt", "readme.md"):
        rp = os.path.join(resolved, rf)
        if os.path.isfile(rp):
            try:
                readme_snippet = Path(rp).read_text(encoding="utf-8", errors="replace")[:800]
            except OSError:
                pass
            break
    return {
        "ok": True,
        "path": path,
        "root_name": os.path.basename(resolved),
        "top_level": top_level,
        "manifests": manifests,
        "readme_snippet": readme_snippet,
        "note": "vibe-coding 未安装，使用轻量级扫描",
    }


def _management_read_scope_error(
    workspace_root: str,
    path: str,
    ctx: Mapping[str, Any],
    *,
    allow_scope_ancestor: bool,
) -> str:
    operation_context = ctx.get("management_work_operation_context")
    if not isinstance(operation_context, dict) or not operation_context.get("task_id"):
        return ""
    resolved = _guard_path(workspace_root, path)
    if resolved is None:
        return "路径越界"
    candidate = Path(resolved)
    lowered_parts = {part.lower() for part in candidate.parts}
    sensitive_name = any(
        part == ".env"
        or part.startswith(".env.")
        or any(marker in part for marker in ("credential", "private_key", "private-key"))
        for part in lowered_parts
    )
    if (
        sensitive_name
        or "_local_secrets" in lowered_parts
        or "secrets" in lowered_parts
        or candidate.suffix.lower() in {".pem", ".key", ".p12", ".pfx"}
    ):
        return "管理员工不得读取密钥或本地机密路径"
    from modstore_server.integrations.doc_sync_handler import _match_glob

    try:
        rel = str(
            candidate.resolve().relative_to(Path(workspace_root).resolve())
        ).replace("\\", "/")
    except ValueError:
        rel = ""
    if not rel and candidate.resolve() != Path(workspace_root).resolve():
        return "路径不在服务端授权仓库内"
    rel = rel.replace("\\", "/").strip("/")
    if rel == ".":
        rel = ""
    forbidden = [
        str(value).strip()
        for value in (ctx.get("forbidden_globs") or [])
        if str(value).strip()
    ]
    scope = [
        str(value).strip()
        for value in (ctx.get("scope_globs") or [])
        if str(value).strip()
    ]
    if forbidden and _match_glob(rel, forbidden):
        return "路径命中岗位 forbidden_globs"
    if not scope or _match_glob(rel, scope):
        return ""
    if allow_scope_ancestor:
        for pattern in scope:
            prefix = re.split(r"[*?[]", pattern.replace("\\", "/"), maxsplit=1)[
                0
            ].rstrip("/")
            if not rel or prefix == rel or prefix.startswith(f"{rel}/"):
                return ""
    return "路径不在岗位 scope_globs 允许范围内"


# ── EmployeeAgentRunner ───────────────────────────────────────────────────────


class EmployeeAgentRunner:
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

    def __init__(
        self,
        ctx: Dict[str, Any],
        *,
        max_rounds: int = 10,
        workspace_root: Optional[str] = None,
    ) -> None:
        self.ctx = ctx
        self.max_rounds = max_rounds
        self.workspace_root = workspace_root or str(ctx.get("workspace_root") or ".")

    # ── public ────────────────────────────────────────────────────────────────

    async def run(
        self,
        task: str,
        *,
        system_prompt: str = "",
        extra_history: Optional[List[Dict[str, str]]] = None,
    ) -> Dict[str, Any]:
        """Execute *task* using the ReAct loop.

        Returns::

            {
              "ok": bool,
              "summary": str,          # final answer or error message
              "rounds": int,           # number of LLM calls made
              "tool_calls": [...],     # list of {tool, input, result}
              "error": str | None,
            }
        """
        protocol = TOOL_PROTOCOL_HEADER.format(max_rounds=self.max_rounds)
        if self.ctx.get("research_tools_enabled"):
            protocol = protocol.rstrip() + RESEARCH_TOOLS_APPEND
        messages: List[Dict[str, str]] = []

        if system_prompt:
            messages.append({"role": "system", "content": system_prompt.strip()})
        messages.append({"role": "system", "content": protocol})

        for msg in extra_history or []:
            messages.append(msg)

        messages.append(
            {
                "role": "user",
                "content": (
                    f"{task.strip()}\n\n"
                    f"（工作区根目录：{self.workspace_root}，可通过 read_workspace_file 等工具访问）"
                ),
            }
        )

        tool_calls_log: List[Dict[str, Any]] = []

        for round_n in range(self.max_rounds):
            resp = await self._call_llm(messages)
            if not resp.get("ok"):
                return {
                    "ok": False,
                    "summary": resp.get("error") or "LLM 调用失败",
                    "rounds": round_n,
                    "tool_calls": tool_calls_log,
                    "error": resp.get("error"),
                }

            raw = resp["content"].strip()
            messages.append({"role": "assistant", "content": raw})

            parsed = _try_parse_json(raw)

            # Final answer branch
            if parsed is not None and "answer" in parsed:
                return {
                    "ok": True,
                    "summary": str(parsed["answer"]),
                    "rounds": round_n + 1,
                    "tool_calls": tool_calls_log,
                    "error": None,
                }

            # Not JSON or missing 'tool' key → treat as final answer
            if parsed is None or "tool" not in parsed:
                return {
                    "ok": True,
                    "summary": raw,
                    "rounds": round_n + 1,
                    "tool_calls": tool_calls_log,
                    "error": None,
                }

            # Tool call branch
            tool_name = str(parsed.get("tool") or "")
            tool_input = parsed.get("input") or {}

            logger.info(
                "[agent:%s] round=%d tool=%s input_keys=%s",
                self.ctx.get("employee_id", "?"),
                round_n + 1,
                tool_name,
                list(tool_input.keys())[:6],
            )

            # Retry identity must not depend on how many reasoning rounds the
            # model took. kind+target already distinguish separate resources;
            # a changed request for the same tool/target conflicts fail-closed.
            self.ctx["management_operation_step"] = f"tool:{tool_name}"
            result = await self._dispatch_tool(tool_name, tool_input)
            tool_calls_log.append({"tool": tool_name, "input": tool_input, "result": result})

            messages.append(
                {
                    "role": "user",
                    "content": json.dumps({"tool_result": result}, ensure_ascii=False),
                }
            )

        # Exhausted rounds — ask for a final summary
        messages.append(
            {
                "role": "user",
                "content": (
                    "已达到最大工具调用轮次，请根据目前的结果给出最终答案。"
                    '输出格式：{"thought":"...", "answer":"..."}'
                ),
            }
        )
        resp = await self._call_llm(messages, max_tokens=1500)
        parsed = _try_parse_json(resp.get("content") or "") if resp.get("ok") else None
        final = (
            (parsed or {}).get("answer")
            or resp.get("content")
            or "已达到最大轮次，请查看工具调用日志"
        )
        return {
            "ok": True,
            "summary": str(final),
            "rounds": self.max_rounds,
            "tool_calls": tool_calls_log,
            "error": None,
        }

    # ── private: tool dispatch ────────────────────────────────────────────────

    async def _dispatch_tool(self, name: str, input_data: Dict[str, Any]) -> Dict[str, Any]:
        try:
            wr = self.workspace_root
            if name == "read_workspace_file":
                path = str(input_data.get("path") or "")
                scope_error = _management_read_scope_error(
                    wr, path, self.ctx, allow_scope_ancestor=False
                )
                if scope_error:
                    return {"ok": False, "error": scope_error}
                return await tool_read_workspace_file(wr, path, self.ctx)

            if name == "write_workspace_file":
                path = str(input_data.get("path") or "")
                content = str(input_data.get("content") or "")
                return await tool_write_workspace_file(wr, path, content, self.ctx)

            if name == "list_workspace_dir":
                path = str(input_data.get("path") or ".")
                scope_error = _management_read_scope_error(
                    wr, path, self.ctx, allow_scope_ancestor=True
                )
                if scope_error:
                    return {"ok": False, "error": scope_error}
                return await tool_list_workspace_dir(wr, path)

            if name == "scan_project_tree":
                path = str(input_data.get("path") or ".")
                scope_error = _management_read_scope_error(
                    wr, path, self.ctx, allow_scope_ancestor=False
                )
                if scope_error:
                    return {"ok": False, "error": scope_error}
                max_files = int(input_data.get("max_files") or 200)
                return await tool_scan_project_tree(wr, path, max_files=max_files)

            if name == "identify_file_types":
                path = str(input_data.get("path") or ".")
                scope_error = _management_read_scope_error(
                    wr, path, self.ctx, allow_scope_ancestor=False
                )
                if scope_error:
                    return {"ok": False, "error": scope_error}
                return await tool_identify_file_types(wr, path)

            if name == "analyze_project_summary":
                path = str(input_data.get("path") or ".")
                scope_error = _management_read_scope_error(
                    wr, path, self.ctx, allow_scope_ancestor=False
                )
                if scope_error:
                    return {"ok": False, "error": scope_error}
                return await tool_analyze_project_summary(wr, path)

            if name == "run_sandboxed_python":
                if isinstance(
                    self.ctx.get("management_work_operation_context"), dict
                ):
                    return {
                        "ok": False,
                        "error": "管理任务禁止未登记副作用的 Python 执行",
                    }
                code = str(input_data.get("code") or "")
                return await tool_run_sandboxed_python(code)

            if name == "http_get":
                fn = self.ctx.get("http_get")
                if not callable(fn):
                    return {"ok": False, "error": "ctx.http_get 未注入"}
                url = str(input_data.get("url") or "")
                headers = input_data.get("headers") or {}
                return await fn(url, headers=headers)

            if name == "http_post":
                fn = self.ctx.get("http_post")
                if not callable(fn):
                    return {"ok": False, "error": "ctx.http_post 未注入"}
                url = str(input_data.get("url") or "")
                body = input_data.get("json_body") or input_data.get("body") or {}
                return await fn(url, json_body=body)

            if name == "internet_search":
                if not self.ctx.get("research_tools_enabled"):
                    return {
                        "ok": False,
                        "error": "联网检索工具未启用（MODSTORE_AGENT_RESEARCH_TOOLS_ENABLED）",
                    }
                from modstore_server.research_tools import internet_search_tool

                q = str(input_data.get("query") or "")
                mr = int(input_data.get("max_results") or 8)
                return await internet_search_tool(q, max_results=max(1, min(mr, 12)))

            if name == "github_repo_snapshot":
                if not self.ctx.get("research_tools_enabled"):
                    return {
                        "ok": False,
                        "error": "GitHub 工具未启用（MODSTORE_AGENT_RESEARCH_TOOLS_ENABLED）",
                    }
                from modstore_server.research_tools import github_repo_snapshot_tool

                return await github_repo_snapshot_tool(
                    str(input_data.get("owner") or ""),
                    str(input_data.get("repo") or ""),
                )

            if name == "call_llm":
                messages = input_data.get("messages") or []
                return await self._call_llm(messages)

            return {"ok": False, "error": f"未知工具：{name!r}"}

        except Exception as exc:  # noqa: BLE001
            logger.exception("agent tool dispatch error tool=%s", name)
            return {"ok": False, "error": str(exc)[:300]}

    async def _call_llm(
        self,
        messages: List[Dict[str, str]],
        *,
        max_tokens: int = 2048,
        temperature: float = 0.2,
    ) -> Dict[str, Any]:
        fn = self.ctx.get("call_llm")
        if not callable(fn):
            return {"ok": False, "content": "", "error": "ctx.call_llm 未注入"}
        try:
            return await asyncio.wait_for(
                fn(messages, max_tokens=max_tokens, temperature=temperature),
                timeout=120.0,
            )
        except asyncio.TimeoutError:
            return {"ok": False, "content": "", "error": "LLM 调用超时（120s）"}
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "content": "", "error": str(exc)[:300]}


# ── helpers ───────────────────────────────────────────────────────────────────


def _try_parse_json(text: str) -> Optional[Dict[str, Any]]:
    """Lenient JSON parser: strip fences and try multiple extract strategies."""
    t = (text or "").strip()
    # Strip markdown fences
    if t.startswith("```"):
        t = re.sub(r"^```(?:json)?\s*", "", t, flags=re.I)
        t = re.sub(r"\s*```\s*$", "", t).strip()
    # Try direct parse
    try:
        data = json.loads(t)
        return data if isinstance(data, dict) else None
    except (json.JSONDecodeError, ValueError):
        pass
    # Try to extract first { ... } block
    i = t.find("{")
    j = t.rfind("}")
    if 0 <= i < j:
        try:
            data = json.loads(t[i : j + 1])
            return data if isinstance(data, dict) else None
        except (json.JSONDecodeError, ValueError):
            pass
    return None


def build_agent_runner(ctx: Dict[str, Any], *, max_rounds: int = 10) -> EmployeeAgentRunner:
    """Convenience factory; used by generated blueprints.py."""
    workspace_root = str(ctx.get("workspace_root") or ".")
    return EmployeeAgentRunner(ctx, max_rounds=max_rounds, workspace_root=workspace_root)
