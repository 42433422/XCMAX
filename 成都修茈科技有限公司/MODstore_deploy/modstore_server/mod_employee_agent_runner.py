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
import json
import logging
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional

logger = logging.getLogger(__name__)


def _bounded_env_int(name: str, default: int, *, minimum: int, maximum: int) -> int:
    try:
        value = int(str(os.environ.get(name) or default).strip())
    except (TypeError, ValueError):
        value = default
    return max(minimum, min(maximum, value))


def _default_max_rounds() -> int:
    return _bounded_env_int("MODSTORE_EMPLOYEE_AGENT_MAX_ROUNDS", 4, minimum=1, maximum=10)


def _llm_timeout_seconds() -> float:
    return float(
        _bounded_env_int(
            "MODSTORE_EMPLOYEE_AGENT_LLM_TIMEOUT_SECONDS",
            45,
            minimum=10,
            maximum=120,
        )
    )


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

READ_ONLY_TOOL_PROTOCOL_HEADER = """你是一个执行真实只读巡检的 AI 员工。
每轮必须输出以下两种格式之一的合法 JSON（不加 markdown 围栏，不加解释文字）：

调用工具（任务未完成时）：
{{
  "thought": "当前分析与下一步计划（至少 20 字）",
  "tool": "工具名",
  "input": {{ "path": "." }}
}}

给出最终答案（任务完成时）：
{{
  "thought": "总结真实观察路径",
  "answer": "包含 status、summary、evidence 的 JSON 对象字符串"
}}

本次只提供以下只读工作区工具：
  analyze_project_summary  params: path(str, default=".")
  scan_project_tree        params: path(str, default="."), max_files(int, 200)
  identify_file_types      params: path(str, default=".")
  read_workspace_file      params: path(str)
  list_workspace_dir       params: path(str, default=".")

约束：
1. 每轮只调用一个已展示工具，结果会以 {{"tool_result": {{...}}}} 回传。
2. 最多 {max_rounds} 轮工具调用后必须输出 answer。
3. 禁止捏造工具结果；至少一次只读工具成功后才可报告 success。
4. 若工具返回 ok=false，换用另一个已展示的只读工具；不得猜测或调用未展示工具。
5. 文件路径必须是相对工作区的相对路径，禁止绝对路径和 ".." 越界。
6. 本次没有写入、命令、网络、消息、交接或变更工具，任何此类动作都不可用。
"""

RESEARCH_TOOLS_APPEND = """
  internet_search          params: query(str), max_results(int, 可选默认 8)             — 联网检索摘要（受服务器每日配额限制）
  github_repo_snapshot     params: owner(str), repo(str)                               — GitHub 公开仓库元数据与 README 摘录
"""

LLM_OPS_TOOLS_APPEND = """

【LLM 运维工程师专属工具】
  list_platform_llm_models params: provider(str, 可选), refresh(bool, 默认 false)          — 查询平台统一模型与动态能力目录
  list_llm_cli_status      params: live_probe(bool, 默认 false)                            — 检查 Codex/Cursor/Claude/Trae CLI 安装与真实可用性
  list_available_ai_routes params: refresh(bool), live_cli_probe(bool), live_quota_probe(bool)    — 合并平台模型、额度、CLI 与完整 AI 资产接口目录（assets）
  get_platform_llm_quota params: live_probe(bool, 默认 false)                             — 查询真实额度、24h 用量与可信度分级
  get_platform_llm_route   params: {}                                                   — 查询当前平台 AI 员工运行时路由
  get_llm_route_autopilot  params: {}                                                   — 查询后台主动巡检最近一次决策
  run_llm_route_autopilot  params: reason(str, 可选)                                    — 立即执行额度+健康巡检，必要时自动切换并验证/回滚
  switch_platform_llm_route params: provider(str), model(str), reason(str)              — 探活后立即切换下一次平台 AI 员工调用
  rollback_platform_llm_route params: reason(str, 可选)                            — 探活后回滚到上一个运行时路由

被问到「有哪些可用 AI / 接口 / 资产」时，必须先调用 list_available_ai_routes，
并以返回的 assets 为准汇报：interfaces（HTTP/runtime/CLI）、by_category
（llm/vlm/image/video/audio/embedding/rerank）、providers、cli_assets。
不得凭记忆编造未出现在 assets 中的接口。

切换约束：只能选择平台模型目录中存在、已配置平台密钥且探活成功的模型；
禁止传入 force 绕过目录或健康检查。所有切换都写入审计历史。
模型选型：先检查 models_detailed[].capabilities，按 input_modalities、
output_modalities 和 operations 匹配任务。capability_source=provider_metadata 最可靠；
hybrid/model_id_inference 包含规则推断，对 TTS、视频等非对话能力不得当成员工主聊天路由切换。
媒体接口：生图走 /api/llm/image，生视频走 /api/llm/video；均要求 OpenAI-compat
provider + 目录中对应 category 模型；audio/embedding/rerank 目前以目录发现为主。
CLI 兜底只在平台 API 调用失败时启用，按 Codex、Claude、Cursor、Trae 顺序尝试；
它们在隔离临时目录中以只读/无 YOLO 方式运行，不传递平台 API key。
CLI 仅接线文本对话；Codex 产品侧 image_generation 未接入平台兜底，须在 assets.cli_assets
的 product_capabilities_not_wired 中如实说明。
后台自动驾驶仅在生产显式开启时每 5 分钟检查当前路由；普通 429 只记录不切换，
连续 3 次真实错误且路由已驻留 15 分钟才允许切换，精确额度耗尽可立即切换。
所有切换使用 revision 比较交换，管理员并发操作优先；精确额度优先，其次真实调用探测，再其次本地用量账本。
额度未知必须标为 unknown/usage_only，不得推断为充足。
"""

LLM_OPS_READ_ONLY_TOOLS_APPEND = """

【LLM 运维工程师只读工具】
  list_platform_llm_models params: provider(str, 可选), refresh(false)
  list_llm_cli_status      params: live_probe(false)
  list_available_ai_routes params: refresh(false), live_cli_probe(false), live_quota_probe(false)
  get_platform_llm_quota   params: live_probe(false)
  get_platform_llm_route   params: {}
  get_llm_route_autopilot  params: {}
"""

HOST_CHECKER_TOOLS_APPEND = """

【宿主检查员工专属工具】
  probe_mod_host params: base_url(str, 可选), timeout_seconds(number, 可选) — 对白名单宿主执行只读 GET，检查 /api/mods/、/api/mods/llm-status、/api/version；不会返回密钥值
"""

SELF_CHECKER_TOOLS_APPEND = """

【员工包自检员工专属工具】
  validate_xcemp_package params: xcemp_path(str), timeout_seconds(number, 可选) — 校验工作区内 .xcemp 归档并在独立 cwd、最小环境变量的子进程中运行 validate
"""

_READ_ONLY_AGENT_TOOLS = frozenset(
    {
        "read_workspace_file",
        "list_workspace_dir",
        "scan_project_tree",
        "identify_file_types",
        "analyze_project_summary",
        "call_llm",
        "list_platform_llm_models",
        "list_llm_cli_status",
        "list_available_ai_routes",
        "get_platform_llm_quota",
        "get_platform_llm_route",
        "get_llm_route_autopilot",
    }
)

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
            from modstore_server.integrations.ops_action_handlers import (
                ops_path_allowed,
            )

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
    if sg or fg:
        from modstore_server.employee_scope_policy import (
            relative_path_under_repo,
            validate_agent_repo_write,
        )

        rel_repo = relative_path_under_repo(Path(resolved))
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
            except Exception:
                pass
            return {"ok": False, "error": msg_sc[:400]}

    emp_id = str(ctx.get("employee_id") or "").strip()
    bypass = bool(ctx.get("bypass_change_request"))
    # 每日编排员写工作区日志/摘要，走直写；其余员工统一进 CR 审批链。
    if emp_id and not bypass and emp_id != "daily-orchestrator":
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
        os.makedirs(os.path.dirname(resolved) or ".", exist_ok=True)
        Path(resolved).write_text(content or "", encoding="utf-8")
        return {
            "ok": True,
            "path": path,
            "bytes_written": len((content or "").encode("utf-8")),
        }
    except OSError as exc:
        return {"ok": False, "error": str(exc)[:300]}


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
            [sys.executable, "-c", code],
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
        return {"ok": False, "error": "Python 运行时不可用"}
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
    skip_dirs = {
        ".git",
        "node_modules",
        "__pycache__",
        ".venv",
        "venv",
        "dist",
        "build",
    }
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
        max_rounds: Optional[int] = None,
        workspace_root: Optional[str] = None,
    ) -> None:
        self.ctx = ctx
        self.max_rounds = (
            _default_max_rounds() if max_rounds is None else max(1, min(10, max_rounds))
        )
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
        read_only = bool(self.ctx.get("read_only"))
        protocol = (READ_ONLY_TOOL_PROTOCOL_HEADER if read_only else TOOL_PROTOCOL_HEADER).format(
            max_rounds=self.max_rounds
        )
        if self.ctx.get("research_tools_enabled") and not read_only:
            protocol = protocol.rstrip() + RESEARCH_TOOLS_APPEND
        if str(self.ctx.get("employee_id") or "").strip() == "llm-ops-engineer":
            protocol = protocol.rstrip() + (
                LLM_OPS_READ_ONLY_TOOLS_APPEND if read_only else LLM_OPS_TOOLS_APPEND
            )
        capabilities = {
            str(item).strip()
            for item in self.ctx.get("employee_capabilities") or []
            if str(item).strip()
        }
        if not read_only and "host_probe" in capabilities:
            protocol = protocol.rstrip() + HOST_CHECKER_TOOLS_APPEND
        if not read_only and "xcemp_validate" in capabilities:
            protocol = protocol.rstrip() + SELF_CHECKER_TOOLS_APPEND
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
            "ok": False,
            "summary": str(final),
            "rounds": self.max_rounds,
            "tool_calls": tool_calls_log,
            "error": "已达到最大工具调用轮次，未能完成任务",
            "exit_status": "max_rounds",
            "max_iterations_reached": True,
        }

    # ── private: tool dispatch ────────────────────────────────────────────────

    async def _dispatch_tool(self, name: str, input_data: Dict[str, Any]) -> Dict[str, Any]:
        try:
            if self.ctx.get("read_only") and name not in _READ_ONLY_AGENT_TOOLS:
                return {
                    "ok": False,
                    "blocked": True,
                    "error": f"只读运行模式禁止工具：{name or '?'}",
                }
            employee_id = str(self.ctx.get("employee_id") or "").strip()
            capabilities = {
                str(item).strip()
                for item in self.ctx.get("employee_capabilities") or []
                if str(item).strip()
            }
            if name == "probe_mod_host":
                if "host_probe" not in capabilities or employee_id != "host-checker":
                    return {
                        "ok": False,
                        "error": f"员工 {employee_id or '?'} 无权使用 {name}",
                    }
                from modstore_server.employee_specialized_tools import (
                    configured_host_probe_allowlist,
                    probe_mod_host,
                )

                employee_input = (
                    self.ctx.get("employee_input")
                    if isinstance(self.ctx.get("employee_input"), dict)
                    else {}
                )
                base_url = str(
                    input_data.get("base_url")
                    or employee_input.get("base_url")
                    or employee_input.get("fhd_base")
                    or os.environ.get("FHD_BASE_URL")
                    or ""
                ).strip()
                if not base_url:
                    return {"ok": False, "error": "缺少 base_url 且未配置 FHD_BASE_URL"}
                return await probe_mod_host(
                    base_url,
                    allowed_hosts=configured_host_probe_allowlist(),
                    timeout_seconds=float(input_data.get("timeout_seconds") or 10.0),
                )

            if name == "validate_xcemp_package":
                if "xcemp_validate" not in capabilities or employee_id != "self-checker":
                    return {
                        "ok": False,
                        "error": f"员工 {employee_id or '?'} 无权使用 {name}",
                    }
                from modstore_server.employee_specialized_tools import (
                    validate_xcemp_package,
                )

                employee_input = (
                    self.ctx.get("employee_input")
                    if isinstance(self.ctx.get("employee_input"), dict)
                    else {}
                )
                relative_path = str(
                    input_data.get("xcemp_path") or employee_input.get("xcemp_path") or ""
                ).strip()
                return await validate_xcemp_package(
                    self.workspace_root,
                    relative_path,
                    timeout_seconds=float(input_data.get("timeout_seconds") or 20.0),
                )
            llm_ops_tools = {
                "list_platform_llm_models",
                "list_llm_cli_status",
                "list_available_ai_routes",
                "get_platform_llm_quota",
                "get_platform_llm_route",
                "get_llm_route_autopilot",
                "run_llm_route_autopilot",
                "switch_platform_llm_route",
                "rollback_platform_llm_route",
            }
            if name in llm_ops_tools and employee_id != "llm-ops-engineer":
                return {
                    "ok": False,
                    "error": f"员工 {employee_id or '?'} 无权使用 {name}",
                }

            if name == "list_platform_llm_models":
                from modstore_server.llm_runtime_route import platform_model_catalog

                return await platform_model_catalog(
                    str(input_data.get("provider") or "") or None,
                    refresh=bool(input_data.get("refresh", False))
                    and not bool(self.ctx.get("read_only")),
                )

            if name == "list_llm_cli_status":
                from modstore_server.llm_cli_fallback import cli_status_catalog

                return await cli_status_catalog(
                    live_probe=bool(input_data.get("live_probe", False))
                    and not bool(self.ctx.get("read_only"))
                )

            if name == "list_available_ai_routes":
                from modstore_server.llm_ai_assets import build_ai_asset_inventory
                from modstore_server.llm_cli_fallback import cli_status_catalog
                from modstore_server.llm_quota_monitor import platform_quota_snapshot
                from modstore_server.llm_runtime_route import platform_model_catalog

                platform, cli = await asyncio.gather(
                    platform_model_catalog(
                        refresh=bool(input_data.get("refresh", False))
                        and not bool(self.ctx.get("read_only"))
                    ),
                    cli_status_catalog(
                        live_probe=bool(input_data.get("live_cli_probe", False))
                        and not bool(self.ctx.get("read_only"))
                    ),
                )
                quota = await platform_quota_snapshot(
                    live_probe=bool(input_data.get("live_quota_probe", False))
                    and not bool(self.ctx.get("read_only")),
                    catalog=platform,
                )
                assets = build_ai_asset_inventory(platform, cli, quota)
                return {
                    "ok": bool(
                        platform.get("ok")
                        and cli.get("ok")
                        and quota.get("ok")
                        and assets.get("ok")
                    ),
                    "platform": platform,
                    "quota": quota,
                    "cli_fallback": cli,
                    "assets": assets,
                    "policy": "platform_api_first_then_local_cli",
                }

            if name == "get_platform_llm_route":
                from modstore_server.llm_runtime_route import (
                    read_runtime_route_state,
                    rollback_target,
                )
                from modstore_server.services.llm import resolve_platform_bench_llm

                provider, model = resolve_platform_bench_llm()
                return {
                    "ok": True,
                    "scope": "platform_ai_employees",
                    "state": read_runtime_route_state(),
                    "effective": {"provider": provider, "model": model},
                    "rollback": rollback_target(),
                }

            if name == "get_platform_llm_quota":
                from modstore_server.llm_quota_monitor import platform_quota_snapshot

                return await platform_quota_snapshot(
                    live_probe=bool(input_data.get("live_probe", False))
                    and not bool(self.ctx.get("read_only"))
                )

            if name == "get_llm_route_autopilot":
                from modstore_server.llm_runtime_autopilot import autopilot_status

                return autopilot_status()

            if name == "run_llm_route_autopilot":
                from modstore_server.llm_runtime_autopilot import (
                    reconcile_llm_route_autopilot,
                )

                return await reconcile_llm_route_autopilot(
                    triggered_by=str(input_data.get("reason") or "employee:llm-ops-engineer"),
                    force=False,
                )

            if name == "switch_platform_llm_route":
                from modstore_server.llm_runtime_route import switch_runtime_route

                return await switch_runtime_route(
                    str(input_data.get("provider") or ""),
                    str(input_data.get("model") or ""),
                    actor="employee:llm-ops-engineer",
                    reason=str(input_data.get("reason") or "active model switch"),
                    refresh_catalog=bool(input_data.get("refresh", False)),
                    force=False,
                )

            if name == "rollback_platform_llm_route":
                from modstore_server.llm_runtime_route import rollback_runtime_route

                return await rollback_runtime_route(
                    actor="employee:llm-ops-engineer",
                    reason=str(input_data.get("reason") or "employee requested rollback"),
                    force=False,
                )
            wr = self.workspace_root
            if name == "read_workspace_file":
                path = str(input_data.get("path") or "")
                return await tool_read_workspace_file(wr, path, self.ctx)

            if name == "write_workspace_file":
                path = str(input_data.get("path") or "")
                content = str(input_data.get("content") or "")
                return await tool_write_workspace_file(wr, path, content, self.ctx)

            if name == "list_workspace_dir":
                path = str(input_data.get("path") or ".")
                return await tool_list_workspace_dir(wr, path)

            if name == "scan_project_tree":
                path = str(input_data.get("path") or ".")
                max_files = int(input_data.get("max_files") or 200)
                return await tool_scan_project_tree(wr, path, max_files=max_files)

            if name == "identify_file_types":
                path = str(input_data.get("path") or ".")
                return await tool_identify_file_types(wr, path)

            if name == "analyze_project_summary":
                path = str(input_data.get("path") or ".")
                return await tool_analyze_project_summary(wr, path)

            if name == "run_sandboxed_python":
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
            primary = {"ok": False, "content": "", "error": "ctx.call_llm 未注入"}
            return await self._maybe_cli_fallback(messages, primary)
        try:
            primary = await asyncio.wait_for(
                fn(messages, max_tokens=max_tokens, temperature=temperature),
                timeout=_llm_timeout_seconds(),
            )
            if primary.get("ok"):
                return primary
            return await self._maybe_cli_fallback(messages, primary)
        except asyncio.TimeoutError:
            timeout_s = int(_llm_timeout_seconds())
            primary = {
                "ok": False,
                "content": "",
                "error": f"LLM 调用超时（{timeout_s}s）",
            }
            return await self._maybe_cli_fallback(messages, primary)
        except Exception as exc:  # noqa: BLE001
            primary = {"ok": False, "content": "", "error": str(exc)[:300]}
            return await self._maybe_cli_fallback(messages, primary)

    async def _maybe_cli_fallback(
        self,
        messages: List[Dict[str, str]],
        primary: Dict[str, Any],
    ) -> Dict[str, Any]:
        employee_id = str(self.ctx.get("employee_id") or "").strip()
        if employee_id != "llm-ops-engineer" or not bool(
            self.ctx.get("cli_fallback_enabled", False)
        ):
            return primary
        from modstore_server.llm_cli_fallback import chat_via_cli_fallback

        fallback = await chat_via_cli_fallback(
            messages,
            timeout=min(180.0, max(30.0, _llm_timeout_seconds())),
        )
        fallback["primary_error"] = str(primary.get("error") or "upstream_failed")[:300]
        return fallback


# ── helpers ───────────────────────────────────────────────────────────────────


def _try_parse_json(text: str) -> Optional[Dict[str, Any]]:
    """Lenient JSON parser: strip fences and try multiple extract strategies."""
    t = (text or "").strip()
    # Reasoning models may wrap hidden analysis before the protocol object.
    # Strip complete think blocks so braces or examples inside them cannot
    # swallow the actual ReAct tool call.
    t = re.sub(r"<think\b[^>]*>.*?</think>", "", t, flags=re.I | re.S).strip()
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
    # Scan every object start instead of combining the first ``{`` with the
    # last ``}``.  Prefer ReAct protocol objects (tool/answer), then the last
    # structured result object.
    decoder = json.JSONDecoder()
    candidates: List[tuple[int, int, Dict[str, Any]]] = []
    for index, char in enumerate(t):
        if char != "{":
            continue
        try:
            data, _end = decoder.raw_decode(t[index:])
        except (json.JSONDecodeError, ValueError):
            continue
        if not isinstance(data, dict):
            continue
        score = 4 if "tool" in data else 4 if "answer" in data else 2 if "status" in data else 1
        candidates.append((score, index, data))
    if candidates:
        return max(candidates, key=lambda item: (item[0], item[1]))[2]
    return None


def build_agent_runner(
    ctx: Dict[str, Any], *, max_rounds: Optional[int] = None
) -> EmployeeAgentRunner:
    """Convenience factory; used by generated blueprints.py."""
    workspace_root = str(ctx.get("workspace_root") or ".")
    return EmployeeAgentRunner(ctx, max_rounds=max_rounds, workspace_root=workspace_root)
