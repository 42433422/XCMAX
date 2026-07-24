"""Bridge MODstore duty employees to Para / DevFleet.

The server process cannot call Codex-side MCP tools directly. This handler is
therefore deliberately explicit:

- If ``MODSTORE_PARA_DELEGATE_WEBHOOK`` is configured, it posts a dispatch
  request and trusts only an ``ok=true`` response as executed/accepted.
- If ``MODSTORE_PARA_API_BASE`` is configured, it authenticates against
  Para/DevFleet and creates a real AI subtask on the configured device.
- Otherwise it writes a durable outbox record and returns ``ok=false`` so the
  loop does not report fake success.
"""

from __future__ import annotations

import json
import os
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

import httpx

_PARA_GUEST_AUTH_CACHE: Dict[str, str] = {}
DEFAULT_PARA_WAIT_TIMEOUT_SEC = 1800.0


def _env_bool(name: str, default: str = "0") -> bool:
    return os.environ.get(name, default).strip().lower() in ("1", "true", "yes", "on")


def para_delegate_enabled() -> bool:
    return _env_bool("MODSTORE_PARA_DELEGATE_ENABLED", "1")


def para_delegate_ready_for_dispatch() -> bool:
    return bool(_webhook_url() or _api_base())


def _webhook_url() -> str:
    return (os.environ.get("MODSTORE_PARA_DELEGATE_WEBHOOK") or "").strip()


def _api_base() -> str:
    return (os.environ.get("MODSTORE_PARA_API_BASE") or "").strip().rstrip("/")


def _api_timeout() -> float:
    return float(os.environ.get("MODSTORE_PARA_API_TIMEOUT_SEC", "60"))


def _wait_for_completion_default() -> bool:
    return _env_bool("MODSTORE_PARA_WAIT_FOR_COMPLETION", "1")


def _wait_timeout_sec(req: Dict[str, Any]) -> float:
    raw = req.get("wait_timeout_sec")
    if raw is None:
        raw = os.environ.get("MODSTORE_PARA_WAIT_TIMEOUT_SEC") or str(DEFAULT_PARA_WAIT_TIMEOUT_SEC)
    try:
        return max(5.0, float(raw))
    except (TypeError, ValueError):
        return DEFAULT_PARA_WAIT_TIMEOUT_SEC


def _wait_poll_sec() -> float:
    try:
        return max(1.0, float(os.environ.get("MODSTORE_PARA_WAIT_POLL_SEC", "5")))
    except ValueError:
        return 5.0


def _outbox_dir() -> Path:
    raw = (
        os.environ.get("MODSTORE_PARA_OUTBOX_DIR")
        or os.environ.get("MODSTORE_RUNTIME_DIR")
        or "/tmp/modstore_runtime"
    )
    path = Path(raw).expanduser()
    if path.name != "para_outbox":
        path = path / "para_outbox"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _project_root(input_data: Dict[str, Any]) -> str:
    return str(
        input_data.get("project_root")
        or input_data.get("workspace_root")
        or os.environ.get("MODSTORE_GIT_REPO_ROOT")
        or os.environ.get("MODSTORE_PARA_WORKSPACE_ROOT")
        or os.environ.get("MODSTORE_REPO_ROOT")
        or ""
    ).strip()


def _mode_for_employee(employee_id: str, input_data: Dict[str, Any]) -> str:
    requested = str(input_data.get("para_mode") or input_data.get("mode") or "").strip()
    if requested:
        return requested
    if employee_id == "change-request-auditor":
        return "review"
    if employee_id == "test-qa-runner":
        return "verify"
    if employee_id == "deploy-release-officer":
        return "merge_release"
    return "code"


def _build_request(
    *,
    task: str,
    input_data: Dict[str, Any],
    employee_id: str,
) -> Dict[str, Any]:
    workspace_root = _project_root(input_data)
    mode = _mode_for_employee(employee_id, input_data)
    report_only = _coerce_bool(input_data.get("report_only"), mode in {"review", "verify"})
    branch = (
        str(
            input_data.get("branch")
            or input_data.get("base_branch")
            or os.environ.get("MODSTORE_PARA_BRANCH")
            or "main"
        ).strip()
        or "main"
    )
    return {
        "request_id": uuid.uuid4().hex,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "source": "modstore_employee_loop",
        "employee_id": employee_id,
        "mode": mode,
        "report_only": report_only,
        "title": str(input_data.get("title") or task or "")[:240],
        "task": task,
        "prompt": str(input_data.get("prompt") or task or ""),
        "workspace_root": workspace_root,
        "repo_url": str(
            input_data.get("repo_url") or os.environ.get("MODSTORE_PARA_REPO_URL") or ""
        ),
        "branch": branch,
        "device_id": str(
            input_data.get("device_id") or os.environ.get("MODSTORE_PARA_DEVICE_ID") or ""
        ),
        "tool_name": str(input_data.get("tool_name") or input_data.get("dev_tool") or ""),
        "depends_on": (
            input_data.get("depends_on") if isinstance(input_data.get("depends_on"), list) else []
        ),
        "para_task_id": str(input_data.get("para_task_id") or input_data.get("task_id") or ""),
        "dispatch_line": str(input_data.get("dispatch_line") or ""),
        "priority": str(input_data.get("priority") or ""),
        "action_item_id": input_data.get("action_item_id"),
        "record_id": input_data.get("record_id"),
        "wait_for_para": input_data.get("wait_for_para"),
        "wait_timeout_sec": input_data.get("wait_timeout_sec"),
        "evidence": (
            input_data.get("evidence") if isinstance(input_data.get("evidence"), dict) else {}
        ),
        "raw_input": input_data,
    }


def _public_request(req: Dict[str, Any]) -> Dict[str, Any]:
    return {
        k: req.get(k)
        for k in (
            "request_id",
            "employee_id",
            "mode",
            "title",
            "workspace_root",
            "repo_url",
            "branch",
            "device_id",
            "report_only",
        )
    }


def _write_outbox(req: Dict[str, Any]) -> Path:
    out = (
        _outbox_dir()
        / f"{req.get('created_at', '').replace(':', '').replace('+', 'Z')}-{req['request_id']}.json"
    )
    out.write_text(json.dumps(req, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return out


def _outbox_response(
    req: Dict[str, Any], *, status: str, error: str, queued: bool = True
) -> Dict[str, Any]:
    outbox = _write_outbox(req)
    return {
        "handler": "para_delegate",
        "ok": False,
        "queued": queued,
        "status": status,
        "error": error,
        "outbox_path": str(outbox),
        "request": _public_request(req),
    }


def _allow_local_workdir() -> bool:
    return _env_bool("MODSTORE_PARA_ALLOW_LOCAL_WORKDIR", "0")


def _build_para_prompt(req: Dict[str, Any]) -> str:
    mode = str(req.get("mode") or "code")
    prompt = str(req.get("prompt") or req.get("task") or "").strip()
    report_only = bool(req.get("report_only"))
    guardrail = {
        "review": "只做代码审查和风险定位；不要修改文件，不要提交。",
        "verify": "执行必要验证并输出证据；不要用兜底结果冒充通过。",
        "merge_release": "只执行明确授权的发布/合并步骤；遇到权限或冲突必须停止并报告。",
    }.get(mode, "按任务要求完成代码修改；失败时输出真实阻塞点。")
    if report_only:
        guardrail = (
            "REPORT-ONLY：不要修改业务文件，不要执行 git add/commit/push。"
            "请只输出结构化报告、风险、证据、下一步建议；Para agent 会把报告回写为完成证据。"
        )
    context = [
        "",
        "MODstore loop context:",
        f"- employee_id: {req.get('employee_id') or ''}",
        f"- mode: {mode}",
        f"- report_only: {str(report_only).lower()}",
        f"- workspace_root: {req.get('workspace_root') or ''}",
        f"- action_item_id: {req.get('action_item_id') or ''}",
        f"- record_id: {req.get('record_id') or ''}",
        f"- guardrail: {guardrail}",
    ]
    if report_only:
        return "MODSTORE_REPORT_ONLY=1\nreport_only=true\n\n" + prompt + "\n" + "\n".join(context)
    return prompt + "\n" + "\n".join(context)


def _get_para_token(client: httpx.Client, base: str) -> Dict[str, str]:
    token = (
        os.environ.get("MODSTORE_PARA_AUTH_TOKEN") or os.environ.get("DEVFLEET_AUTH_TOKEN") or ""
    ).strip()
    if token:
        return {"token": token, "source": "env"}

    cached = _PARA_GUEST_AUTH_CACHE.get(base)
    if cached:
        return {"token": cached, "source": "guest_cache"}

    if not _env_bool("MODSTORE_PARA_GUEST_AUTH", "1"):
        raise RuntimeError("MODSTORE_PARA_AUTH_TOKEN 未配置，且 MODSTORE_PARA_GUEST_AUTH=0")

    resp = client.post(f"{base}/api/auth/guest")
    body: Any = {}
    try:
        body = resp.json() if resp.content else {}
    except Exception:
        body = {"raw": resp.text[:1000]}
    if resp.status_code >= 400:
        raise RuntimeError(str(body.get("error") or body.get("detail") or resp.text[:500]))
    guest_token = str(body.get("token") or "").strip()
    if not guest_token:
        raise RuntimeError("Para guest auth response missing token")
    _PARA_GUEST_AUTH_CACHE[base] = guest_token
    return {"token": guest_token, "source": "guest"}


def _summarize_para_response(body: Any) -> Dict[str, Any]:
    if not isinstance(body, dict):
        return {"raw": str(body)[:1000]}
    task = body.get("task") if isinstance(body.get("task"), dict) else {}
    subtask = body.get("subtask") if isinstance(body.get("subtask"), dict) else {}
    if not subtask:
        subtasks = task.get("subTasks") if isinstance(task.get("subTasks"), list) else []
        subtask = subtasks[0] if subtasks and isinstance(subtasks[0], dict) else {}
    return {
        "task_id": task.get("id"),
        "task_status": task.get("status"),
        "subtask_id": subtask.get("id"),
        "subtask_status": subtask.get("status"),
        "progress": subtask.get("progress"),
        "subtask_branch": subtask.get("branch_name"),
        "device_name": subtask.get("device_name"),
        "error": body.get("error") or body.get("detail") or "",
    }


def _para_db_file() -> Path:
    raw = (
        os.environ.get("MODSTORE_PARA_DB_FILE")
        or "~/Library/Application Support/com.devfleet.desktop/devfleet.db"
    )
    return Path(raw).expanduser()


def _force_single_device_attempt(req: Dict[str, Any], accepted: Dict[str, Any]) -> Dict[str, Any]:
    """仅 report_only 强制 max_attempts=1；重负载保留 Para 默认/请求值以便 transient 重试。"""
    if not bool(req.get("report_only")):
        return {"ok": True, "enabled": False, "reason": "heavy_workload_keeps_retries"}
    if not _env_bool("MODSTORE_PARA_DISABLE_AUTO_RETRY", "1"):
        return {"ok": True, "enabled": False}
    task_id = str(accepted.get("task_id") or "").strip()
    subtask_id = str(accepted.get("subtask_id") or "").strip()
    if not task_id or not subtask_id:
        return {"ok": False, "error": "missing task_id/subtask_id"}
    try:
        import sqlite3

        db_file = _para_db_file()
        con = sqlite3.connect(str(db_file))
        try:
            con.execute(
                "update sub_tasks set max_attempts = 1 where id = ? and task_id = ?",
                (subtask_id, task_id),
            )
            con.commit()
        finally:
            con.close()
        return {"ok": True, "enabled": True, "task_id": task_id, "subtask_id": subtask_id}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "enabled": True, "error": str(exc)[:500]}


def _resolve_max_attempts(req: Dict[str, Any]) -> int:
    if bool(req.get("report_only")):
        return 1
    raw = req.get("max_attempts")
    try:
        value = int(raw) if raw is not None else 3
    except (TypeError, ValueError):
        value = 3
    return max(1, min(5, value))


def _git_preflight_branch(repo_url: str, branch: str) -> Dict[str, Any]:
    """派工前校验远程分支；失败则不创建注定失败的任务。"""
    url = (repo_url or "").strip()
    ref = (branch or "main").strip() or "main"
    if not url:
        return {"ok": False, "error": "repo_url 为空", "failure_kind": "git_prep"}
    if url.startswith("file://") or os.environ.get("MODSTORE_PARA_SKIP_GIT_PREFLIGHT") == "1":
        return {"ok": True, "skipped": True}
    try:
        import subprocess

        proc = subprocess.run(
            ["git", "ls-remote", "--heads", "--exit-code", url, ref],
            capture_output=True,
            text=True,
            timeout=float(os.environ.get("MODSTORE_PARA_GIT_PREFLIGHT_SEC") or "12"),
            env={**os.environ, "GIT_TERMINAL_PROMPT": "0"},
            check=False,
        )
        if proc.returncode != 0 or not (proc.stdout or "").strip():
            err = (proc.stderr or proc.stdout or "branch not found").strip()[:500]
            return {
                "ok": False,
                "error": f"Git 预检失败：远程不存在分支 {ref}（{err}）",
                "failure_kind": "git_prep",
            }
        return {"ok": True}
    except Exception as exc:  # noqa: BLE001
        return {
            "ok": False,
            "error": f"Git 预检异常：{exc}"[:500],
            "failure_kind": "git_prep",
        }


def _task_result_snapshot(body: Any) -> Dict[str, Any]:
    if not isinstance(body, dict):
        return {"raw": str(body)[:1000]}
    task = body.get("task") if isinstance(body.get("task"), dict) else {}
    subtasks = task.get("subTasks") if isinstance(task.get("subTasks"), list) else []
    normalized_subtasks = []
    logs_tail = []
    for sub in subtasks:
        if not isinstance(sub, dict):
            continue
        logs = sub.get("logs") if isinstance(sub.get("logs"), list) else []
        for item in logs[-5:]:
            if isinstance(item, dict):
                logs_tail.append(
                    {
                        "level": item.get("level"),
                        "content": str(item.get("content") or "")[:1000],
                        "timestamp": item.get("timestamp"),
                    }
                )
        normalized_subtasks.append(
            {
                "id": sub.get("id"),
                "status": sub.get("status"),
                "progress": sub.get("progress"),
                "branch": sub.get("branch_name"),
                "device_name": sub.get("device_name"),
                "last_error": sub.get("last_error"),
            }
        )
    return {
        "task_id": task.get("id"),
        "task_status": task.get("status"),
        "repo_url": task.get("repo_url"),
        "branch": task.get("branch"),
        "merge_commit_sha": task.get("merge_commit_sha"),
        "merge_conflict": task.get("merge_conflict"),
        "subtasks": normalized_subtasks,
        "logs_tail": logs_tail[-10:],
    }


def _wait_for_para_task(
    client: httpx.Client,
    base: str,
    token: str,
    task_id: str,
    req: Dict[str, Any],
) -> Dict[str, Any]:
    deadline = time.monotonic() + _wait_timeout_sec(req)
    last_body: Any = {}
    terminal = {"completed", "merged", "failed", "merge_conflict"}
    while True:
        resp = client.get(
            f"{base}/api/tasks/{task_id}",
            headers={"Authorization": f"Bearer {token}"},
        )
        try:
            body = resp.json() if resp.content else {}
        except Exception:
            body = {"raw": resp.text[:4000]}
        last_body = body
        if resp.status_code >= 400:
            return {
                "ok": False,
                "status": "para_task_poll_failed",
                "status_code": resp.status_code,
                "error": str(
                    (body.get("error") or body.get("detail") or resp.text[:500])
                    if isinstance(body, dict)
                    else resp.text[:500]
                ),
                "snapshot": _task_result_snapshot(body),
            }
        task = (
            body.get("task")
            if isinstance(body, dict) and isinstance(body.get("task"), dict)
            else {}
        )
        status = str(task.get("status") or "").strip()
        if status in terminal:
            snapshot = _task_result_snapshot(body)
            ok = status in {"completed", "merged"}
            return {
                "ok": ok,
                "status": "para_task_" + (status or "unknown"),
                "error": "" if ok else _first_para_error(snapshot),
                "snapshot": snapshot,
            }
        if time.monotonic() >= deadline:
            snapshot = _task_result_snapshot(last_body)
            return {
                "ok": False,
                "status": "para_task_timeout",
                "error": f"Para task {task_id} 未在 {_wait_timeout_sec(req):.0f}s 内完成",
                "snapshot": snapshot,
            }
        time.sleep(_wait_poll_sec())


def _first_para_error(snapshot: Dict[str, Any]) -> str:
    for sub in snapshot.get("subtasks") or []:
        if not isinstance(sub, dict):
            continue
        err = str(sub.get("last_error") or "").strip()
        if err:
            return err[:1000]
    for item in snapshot.get("logs_tail") or []:
        if not isinstance(item, dict):
            continue
        if str(item.get("level") or "").lower() in {"error", "warn"}:
            return str(item.get("content") or "")[:1000]
    status = str(snapshot.get("task_status") or "").strip()
    return f"Para task status={status or 'unknown'}"


# ── Para 分级派工：一级=本机单设备，二级=多设备协同（与 FHD super_employee_service 同构） ──
#
# loops 后半经此桥接 Para/DevFleet。原先只认单个写死的 MODSTORE_PARA_DEVICE_ID，没配
# 就 outbox。现补齐与 FHD 一致的分级：默认一级优先——发现在线的本机/主设备派单设备；
# 仅当任务显式要多设备并行/分工(max_devices>1 / target_devices 多个 / para_tier=2 /
# escalate / 文本含"多设备"等)或本机不可用时升二级，扇出到多台 worker。显式给了
# device_id 的部署保持原行为不变(零回归)。设备配对+agent 拉起仍属 DevFleet/运维侧。

_SUBTASK_LABELS = ("需求定位与方案", "核心实现", "验证与收尾")


def _fallback_order_tools() -> list[str]:
    configured = os.environ.get(
        "MODSTORE_PARA_TOOL_FALLBACK_ORDER",
        "cursor,claude_code,trae",
    )
    out: list[str] = []
    for value in configured.split(","):
        tool = _normalize_tool_name(value)
        if tool in _VALID_DEV_TOOLS and tool not in out:
            out.append(tool)
    return out


def _dev_tool() -> str:
    """loops 桥默认派给的设备工具(DevFleet devTool)，用于设备过滤。"""
    normalized = _normalize_tool_name(os.environ.get("MODSTORE_PARA_DEV_TOOL") or "")
    if normalized in _VALID_DEV_TOOLS:
        return normalized
    order = _fallback_order_tools()
    return order[0] if order else "cursor"


_VALID_DEV_TOOLS = ("codex", "claude_code", "cursor", "trae")
_TOOL_INPUT_ALIASES = {
    "claude": "claude_code",
    "claude-code": "claude_code",
    "cursor_agent": "cursor",
    "cursor-agent": "cursor",
}

# DevFleet / Mac Bridge 上报的 capability / toolName 与调度侧命名不完全一致。
_TOOL_CAP_ALIASES: Dict[str, tuple[str, ...]] = {
    "codex": ("codex_cli",),
    "cursor": ("cursor_cli", "cursor_agent_cli", "cursor-agent_cli"),
    "claude_code": ("claude_code_cli", "claude_cli", "claude-code_cli"),
    "trae": ("trae_cli",),
}
_TOOL_NAME_ALIASES: Dict[str, tuple[str, ...]] = {
    "codex": ("codex",),
    "cursor": ("cursor", "cursor_agent", "cursor-agent"),
    "claude_code": ("claude_code", "claude", "claude-code"),
    "trae": ("trae",),
}


def _normalize_tool_name(name: str) -> str:
    raw = str(name or "").strip()
    if not raw:
        return ""
    if raw in _VALID_DEV_TOOLS:
        return raw
    return _TOOL_INPUT_ALIASES.get(raw, raw)


def _tool_fallback_allowed(req: Dict[str, Any]) -> bool:
    """Whether CLI runtime failure may retry another tool.

    ``allow_tool_fallback=0`` pins the requested tool.  Otherwise the env master
    switch wins — an explicit ``tool_name`` no longer silently disables recovery
    (that previously left ``spawn codex ENOENT`` storms with no fallback).
    """
    raw = req.get("raw_input") if isinstance(req.get("raw_input"), dict) else {}
    raw_fallback = raw.get("allow_tool_fallback")
    if raw_fallback is None and "allow_tool_fallback" not in req:
        return _env_bool("MODSTORE_PARA_TOOL_FALLBACK_ENABLED", "1")
    value = raw_fallback if raw_fallback is not None else req.get("allow_tool_fallback")
    return str(value).strip().lower() in ("1", "true", "yes", "on")


def _excluded_tools(req: Dict[str, Any]) -> set[str]:
    raw = req.get("raw_input") if isinstance(req.get("raw_input"), dict) else {}
    excluded: set[str] = set()
    for key in ("_para_exclude_tools", "para_exclude_tools"):
        blob = raw.get(key)
        if isinstance(blob, (list, tuple, set)):
            excluded.update(str(item or "").strip() for item in blob if str(item or "").strip())
    top = req.get("_para_exclude_tools")
    if isinstance(top, (list, tuple, set)):
        excluded.update(str(item or "").strip() for item in top if str(item or "").strip())
    return {item for item in excluded if item in _VALID_DEV_TOOLS}


def _tool_candidates(req: Dict[str, Any]) -> list[str]:
    """Return the preferred executor followed by allowed same-device fallbacks.

    With fallback enabled, an explicit tool stays first but other tools from
    ``MODSTORE_PARA_TOOL_FALLBACK_ORDER`` remain eligible.  Without an explicit
    tool, the fallback order itself is the preference list (no silent codex
    prepend).  Pin with ``allow_tool_fallback=0`` for strict single-tool mode.
    """
    raw = req.get("raw_input") if isinstance(req.get("raw_input"), dict) else {}
    explicit = _normalize_tool_name(
        str(req.get("tool_name") or raw.get("tool_name") or raw.get("dev_tool") or "")
    )
    preferred = explicit if explicit in _VALID_DEV_TOOLS else _dev_tool()
    order = _fallback_order_tools()

    if not _tool_fallback_allowed(req):
        candidates = [preferred]
    elif explicit:
        candidates = [explicit] + [tool for tool in order if tool != explicit]
    else:
        candidates = list(order) if order else [preferred]
        if preferred not in candidates:
            candidates.insert(0, preferred)

    excluded = _excluded_tools(req)
    return [tool for tool in candidates if tool not in excluded]


def _is_cli_runtime_failure(
    *,
    error: str = "",
    status: str = "",
    snapshot: Any = None,
    api_error: str = "",
) -> bool:
    """True when the chosen CLI is missing/broken and another tool may succeed."""

    parts = [str(error or ""), str(status or ""), str(api_error or "")]
    if isinstance(snapshot, dict):
        parts.append(str(snapshot.get("task_status") or ""))
        for sub in snapshot.get("subtasks") or []:
            if isinstance(sub, dict):
                parts.append(str(sub.get("last_error") or ""))
                parts.append(str(sub.get("status") or ""))
        for item in snapshot.get("logs_tail") or []:
            if isinstance(item, dict):
                parts.append(str(item.get("content") or ""))
    text = " ".join(parts).lower()
    needles = (
        "enoent",
        "not_installed",
        "not installed",
        "command not found",
        "no such file",
        "spawn codex",
        "spawn cursor",
        "spawn claude",
        "spawn trae",
        "codex cli",
        "cursor cli",
        "claude cli",
        "trae cli",
        "cli 失败",
        "cli failed",
        "executable not found",
        "is not recognized",
    )
    return any(token in text for token in needles)


def _device_discovery_enabled() -> bool:
    return _env_bool("MODSTORE_PARA_DEVICE_DISCOVERY", "1")


def _safe_json(resp: httpx.Response) -> Any:
    try:
        return resp.json() if resp.content else {}
    except Exception:
        return {"raw": resp.text[:4000]}


def _device_tool_entry(item: Dict[str, Any], tool_name: str) -> Optional[Dict[str, Any]]:
    tools = item.get("tools")
    if not isinstance(tools, list):
        return None
    aliases = _TOOL_NAME_ALIASES.get(tool_name, (tool_name,))
    for tool in tools:
        if not isinstance(tool, dict):
            continue
        name = str(tool.get("toolName") or tool.get("name") or "").strip()
        if name in aliases:
            return tool
    return None


def _device_has_capability(caps: Dict[str, Any], tool_name: str) -> bool:
    for key in _TOOL_CAP_ALIASES.get(tool_name, (f"{tool_name}_cli",)):
        if caps.get(key) is True:
            return True
    return False


def _device_eligible(item: Any, tool_name: str) -> bool:
    """设备能否承接派工：在线 + 目标工具已装且非占用（executorReady）。"""
    if not isinstance(item, dict):
        return False
    if str(item.get("status") or "") != "online":
        return False
    # 显式 executorReady=false 直接拒绝
    if item.get("executorReady") is False:
        return False
    tool = _device_tool_entry(item, tool_name)
    if tool and str(tool.get("status") or "") == "not_installed":
        return False
    if tool and str(tool.get("status") or "") == "running" and tool.get("currentTask"):
        return False
    if not tool:
        caps = item.get("capabilities") if isinstance(item.get("capabilities"), dict) else {}
        if _device_has_capability(caps, tool_name):
            return True
        # 无 tools 列表时，仅当声明的 devTool 匹配才视为就绪（避免盲派到缺 CLI 设备）
        dev_tool = str(item.get("devTool") or "").strip()
        aliases = _TOOL_NAME_ALIASES.get(tool_name, (tool_name,))
        return dev_tool in aliases
    return True


def _selected_tool_for_device(item: Any, req: Dict[str, Any]) -> str:
    for tool_name in _tool_candidates(req):
        if _device_eligible(item, tool_name):
            return tool_name
    return ""


def _with_selected_tool(item: Dict[str, Any], tool_name: str) -> Dict[str, Any]:
    return {**item, "_selected_tool": tool_name}


def _select_local_device_with_fallback(devices: list, req: Dict[str, Any]) -> list:
    local_id = (os.environ.get("MODSTORE_PARA_DEVICE_ID") or "").strip()
    ordered: list = []
    if local_id:
        ordered.extend(
            item
            for item in devices
            if isinstance(item, dict) and str(item.get("id") or "") == local_id
        )
    else:
        primary = [item for item in devices if isinstance(item, dict) and item.get("isPrimary")]
        ordered.extend(primary or [item for item in devices if isinstance(item, dict)])
    for item in ordered:
        selected_tool = _selected_tool_for_device(item, req)
        if selected_tool:
            return [_with_selected_tool(item, selected_tool)]
    return []


def _select_fleet_devices_with_fallback(devices: list, req: Dict[str, Any]) -> list:
    raw = req.get("raw_input") if isinstance(req.get("raw_input"), dict) else {}
    target = raw.get("target_devices")
    targets = (
        {str(x).strip() for x in target if str(x).strip()} if isinstance(target, list) else {"all"}
    )
    candidates: list = []
    for item in devices:
        if not isinstance(item, dict):
            continue
        if (
            "all" not in targets
            and str(item.get("id") or "") not in targets
            and str(item.get("name") or "") not in targets
        ):
            continue
        selected_tool = _selected_tool_for_device(item, req)
        if selected_tool:
            candidates.append(_with_selected_tool(item, selected_tool))
    workers = [item for item in candidates if not item.get("isPrimary")]
    return (workers or candidates)[: _max_fleet_devices(req)]


def _filter_executor_ready(devices: list, tool_name: str) -> list:
    return [item for item in devices if _device_eligible(item, tool_name)]


def _resolve_tier(req: Dict[str, Any]) -> int:
    """一级(1) / 二级(2)。默认一级，按需升二级。读 req.raw_input + 任务文本。"""
    forced = (os.environ.get("MODSTORE_PARA_FORCE_TIER") or "").strip().lower()
    if forced in {"1", "local", "single", "本机"}:
        return 1
    if forced in {"2", "fleet", "multi", "多设备"}:
        return 2
    raw = req.get("raw_input") if isinstance(req.get("raw_input"), dict) else {}
    hint = str(raw.get("para_tier") or raw.get("tier") or "").strip().lower()
    if hint in {"2", "fleet", "multi", "multi_device", "多设备"}:
        return 2
    if hint in {"1", "local", "single", "本机"}:
        return 1
    if raw.get("escalate") in (True, 1, "1", "true", "yes", "on"):
        return 2
    try:
        if int(raw.get("max_devices") or 0) > 1:
            return 2
    except (TypeError, ValueError):
        pass
    target = raw.get("target_devices")
    if isinstance(target, list):
        specific = [s for s in (str(x).strip() for x in target) if s and s != "all"]
        if len(specific) > 1:
            return 2
    text = f"{req.get('task') or ''} {req.get('prompt') or ''}"
    if any(m in text for m in ("多设备", "所有设备", "全部设备", "调用所有设备", "跨设备")):
        return 2
    return 1


def _max_fleet_devices(req: Dict[str, Any]) -> int:
    raw = req.get("raw_input") if isinstance(req.get("raw_input"), dict) else {}
    try:
        return max(1, min(8, int(raw.get("max_devices") or 3)))
    except (TypeError, ValueError):
        return 3


def _select_local_device(devices: list, tool_name: str) -> list:
    """一级：只挑「本机」一台。配置 MODSTORE_PARA_DEVICE_ID → is_primary → 首台合格。
    识别到的本机若不合格(离线/工具未装/占用)则返空，由上层升二级。"""
    local_id = (
        os.environ.get("MODSTORE_PARA_DEVICE_ID") or os.environ.get("DEVFLEET_DEVICE_ID") or ""
    ).strip()
    if local_id:
        for item in devices:
            if isinstance(item, dict) and str(item.get("id") or "") == local_id:
                return [item] if _device_eligible(item, tool_name) else []
        return []
    for item in devices:
        if isinstance(item, dict) and item.get("isPrimary"):
            return [item] if _device_eligible(item, tool_name) else []
    for item in devices:
        if _device_eligible(item, tool_name):
            return [item]
    return []


def _select_fleet_devices(devices: list, req: Dict[str, Any], tool_name: str) -> list:
    """二级：选多台在线设备(偏好非主 worker)，受 target_devices / max_devices 约束。"""
    raw = req.get("raw_input") if isinstance(req.get("raw_input"), dict) else {}
    target = raw.get("target_devices")
    targets = (
        {str(x).strip() for x in target if str(x).strip()} if isinstance(target, list) else {"all"}
    )
    candidates: list = []
    for item in devices:
        if not _device_eligible(item, tool_name):
            continue
        if (
            "all" not in targets
            and str(item.get("id") or "") not in targets
            and str(item.get("name") or "") not in targets
        ):
            continue
        candidates.append(item)
    workers = [item for item in candidates if not item.get("isPrimary")]
    selected = workers or candidates
    return selected[: _max_fleet_devices(req)]


def _fetch_devices(client: httpx.Client, base: str, token: str) -> list:
    try:
        resp = client.get(
            f"{base}/api/devices",
            headers={"Authorization": f"Bearer {token}"},
        )
    except Exception:
        return []
    if resp.status_code >= 400:
        return []
    body = _safe_json(resp)
    devices = body.get("devices") if isinstance(body, dict) else []
    return devices if isinstance(devices, list) else []


def _resolve_dispatch_devices(
    client: httpx.Client, base: str, token: str, req: Dict[str, Any]
) -> tuple:
    """返回 (tier, [device dicts], reason)。显式 device_id → 零回归走一级单设备。"""
    explicit = str(req.get("device_id") or "").strip()
    if explicit:
        devices = _fetch_devices(client, base, token)
        target = next(
            (
                item
                for item in devices
                if isinstance(item, dict) and str(item.get("id") or "") == explicit
            ),
            None,
        )
        if target is not None:
            selected_tool = _selected_tool_for_device(target, req)
            if selected_tool:
                return 1, [_with_selected_tool(target, selected_tool)], ""
        # Preserve the explicit-device contract when discovery is unavailable or
        # every executor is busy: Para may queue the preferred tool safely.
        return 1, [{"id": explicit, "_selected_tool": _tool_candidates(req)[0]}], ""
    if not _device_discovery_enabled():
        return (
            1,
            [],
            "未配置 MODSTORE_PARA_DEVICE_ID 且设备发现关闭(MODSTORE_PARA_DEVICE_DISCOVERY=0)",
        )
    devices = _fetch_devices(client, base, token)
    tier = _resolve_tier(req)
    if tier == 1:
        # 优先走同设备多 CLI 候选；避免「preferred 看似可用」时跳过 idle fallback。
        local = _select_local_device_with_fallback(devices, req)
        if local:
            return 1, local, ""
        preferred = (_tool_candidates(req) or [_dev_tool()])[0]
        local = _select_local_device(devices, preferred)
        if local:
            return 1, [_with_selected_tool(local[0], preferred)], ""
        tier = 2  # 本机不可用 → 升二级
    selected = _select_fleet_devices_with_fallback(devices, req)
    if not selected:
        preferred = (_tool_candidates(req) or [_dev_tool()])[0]
        selected = [
            _with_selected_tool(item, preferred)
            for item in _select_fleet_devices(devices, req, preferred)
        ]
    if not selected:
        tools = ",".join(_tool_candidates(req)) or _dev_tool()
        return tier, [], f"未发现在线可用 {tools} 执行器(共 {len(devices)} 台设备)"
    return tier, selected, ""


def _multi_device_prompt(base_prompt: str, device: Dict[str, Any], index: int, total: int) -> str:
    if total <= 1:
        return base_prompt
    label = device.get("name") or device.get("id") or f"设备{index + 1}"
    suffix = (
        f"\n\n你是第 {index + 1}/{total} 台工作设备（{label}）。"
        "请承担可独立完成的部分，避免与其它设备改同一批文件；提交到调度器分配的分支并回写日志。"
    )
    return base_prompt + suffix


def _para_subtask_title(req: Dict[str, Any], index: int, total: int) -> str:
    title = str(req.get("title") or "MODstore loop task")
    if total <= 1:
        return f"{req.get('mode') or 'code'}: {title}"[:240]
    label = _SUBTASK_LABELS[index] if index < len(_SUBTASK_LABELS) else f"工作单元{index + 1}"
    return f"{label}：{title[:60]}"


def _req_with_excluded_tools(req: Dict[str, Any], excluded: set[str]) -> Dict[str, Any]:
    work = dict(req or {})
    raw = dict(work.get("raw_input") or {}) if isinstance(work.get("raw_input"), dict) else {}
    merged = sorted((set(excluded) | _excluded_tools(work)))
    raw["_para_exclude_tools"] = merged
    work["raw_input"] = raw
    work["_para_exclude_tools"] = merged
    # 换 CLI 必须新开 task，避免复用已失败的 subtask
    work.pop("para_task_id", None)
    return work


def _attach_tool_fallback_meta(
    result: Dict[str, Any],
    *,
    attempts: list,
) -> Dict[str, Any]:
    if not isinstance(result, dict):
        return result
    if attempts:
        result["tool_fallback_attempts"] = list(attempts)
        result["tool_fallback_used"] = True
    return result


def _post_para_api(req: Dict[str, Any]) -> Dict[str, Any]:
    attempts: list = []
    excluded: set[str] = set(_excluded_tools(req))
    result = _post_para_api_once(req)
    max_attempts = _resolve_max_attempts(req)
    for _ in range(max_attempts):
        if bool(result.get("ok")):
            return _attach_tool_fallback_meta(result, attempts=attempts)
        if not _tool_fallback_allowed(req):
            return _attach_tool_fallback_meta(result, attempts=attempts)
        used_tool = ""
        for item in result.get("devices") or []:
            if isinstance(item, dict) and str(item.get("tool_name") or "").strip():
                used_tool = str(item.get("tool_name") or "").strip()
                break
        if not used_tool:
            used_tool = str(
                (result.get("request") or {}).get("tool_name")
                if isinstance(result.get("request"), dict)
                else ""
            ).strip()
        if used_tool not in _VALID_DEV_TOOLS:
            # 从 payload / 候选里推断刚失败的首选工具
            candidates = _tool_candidates(_req_with_excluded_tools(req, excluded))
            used_tool = candidates[0] if candidates else ""
        if not used_tool or used_tool in excluded:
            return _attach_tool_fallback_meta(result, attempts=attempts)
        if not _is_cli_runtime_failure(
            error=str(result.get("error") or ""),
            status=str(result.get("status") or ""),
            snapshot=result.get("para_result"),
            api_error=str(result.get("error") or ""),
        ):
            return _attach_tool_fallback_meta(result, attempts=attempts)
        attempts.append(
            {
                "tool_name": used_tool,
                "status": result.get("status"),
                "error": str(result.get("error") or "")[:500],
            }
        )
        excluded.add(used_tool)
        next_req = _req_with_excluded_tools(req, excluded)
        if not _tool_candidates(next_req):
            return _attach_tool_fallback_meta(result, attempts=attempts)
        logger_msg = (
            f"para tool runtime failure tool={used_tool}; retry with "
            f"{','.join(_tool_candidates(next_req))}"
        )
        try:
            import logging

            logging.getLogger(__name__).warning(logger_msg)
        except Exception:
            pass
        result = _post_para_api_once(next_req)
    return _attach_tool_fallback_meta(result, attempts=attempts)


def _post_para_api_once(req: Dict[str, Any]) -> Dict[str, Any]:
    base = _api_base()
    if not base:
        return _outbox_response(
            req,
            status="awaiting_para_dispatcher",
            error="MODSTORE_PARA_API_BASE 未配置；已写入 outbox，但未真实派发到 Para",
        )

    repo_url = str(req.get("repo_url") or "").strip()
    if not repo_url and not _allow_local_workdir():
        return _outbox_response(
            req,
            status="blocked_missing_repo_url",
            error=(
                "缺少 repo_url；已拒绝让 Para 使用工作设备本地目录，避免污染设备工作区。"
                "请配置 MODSTORE_PARA_REPO_URL 或在任务输入里提供 repo_url；"
                "如确实要使用设备本地目录，显式设置 MODSTORE_PARA_ALLOW_LOCAL_WORKDIR=1。"
            ),
            queued=False,
        )

    branch = str(req.get("branch") or "main").strip() or "main"
    report_only = bool(req.get("report_only"))
    if repo_url and not report_only and not _allow_local_workdir():
        git_check = _git_preflight_branch(repo_url, branch)
        if not git_check.get("ok"):
            return _outbox_response(
                req,
                status="blocked_git_preflight",
                error=str(git_check.get("error") or "git preflight failed"),
                queued=True,  # transient outbox：仓库/分支恢复后可重放
            )

    base_prompt = _build_para_prompt(req)
    first_payload: Dict[str, Any] = {}
    max_attempts = _resolve_max_attempts(req)
    # 低风险自维护/verify 可自动 merge；Incident fix 默认不自动 merge
    mode = str(req.get("mode") or "").strip().lower()
    auto_merge = bool(req.get("auto_merge"))
    if not auto_merge and mode in {"verify", "review", "report"} and report_only is False:
        auto_merge = _coerce_bool(req.get("auto_merge_on_complete"), False)
    workspace_path = str(
        req.get("workspace_path") or os.environ.get("MODSTORE_PARA_WORKSPACE_PATH") or ""
    ).strip()
    try:
        with httpx.Client(timeout=_api_timeout(), trust_env=False) as client:
            token_info = _get_para_token(client, base)
            token = token_info["token"]

            tier, sel_devices, select_reason = _resolve_dispatch_devices(client, base, token, req)
            if not sel_devices:
                return _outbox_response(
                    req,
                    status="blocked_no_online_para_device",
                    error=select_reason or "未发现在线可用 Para 工作设备（executorReady）",
                    queued=True,
                )

            total = len(sel_devices)
            task_id = str(req.get("para_task_id") or "").strip()
            dispatched: list = []
            for index, device in enumerate(sel_devices):
                device_id = str(device.get("id") or "").strip()
                if not device_id:
                    continue
                payload: Dict[str, Any] = {
                    "device_id": device_id,
                    "title": str(req.get("title") or "MODstore loop task").strip(),
                    "prompt": _multi_device_prompt(base_prompt, device, index, total),
                    "branch": branch,
                    "subtask_title": _para_subtask_title(req, index, total),
                    "report_only": report_only,
                    "max_attempts": max_attempts,
                }
                selected_tool = str(device.get("_selected_tool") or "").strip()
                if selected_tool:
                    payload["tool_name"] = selected_tool
                if repo_url:
                    payload["repo_url"] = repo_url
                if auto_merge:
                    payload["auto_merge"] = True
                if workspace_path:
                    payload["workspace_path"] = workspace_path
                if isinstance(req.get("depends_on"), list) and req.get("depends_on"):
                    payload["depends_on"] = req.get("depends_on")
                if task_id:
                    payload["task_id"] = task_id
                if not first_payload:
                    first_payload = payload

                resp = client.post(
                    f"{base}/api/tasks",
                    headers={"Authorization": f"Bearer {token}"},
                    json=payload,
                )
                body = _safe_json(resp)
                ok = (
                    resp.status_code < 400
                    and isinstance(body, dict)
                    and bool(body.get("task") or body.get("subtask"))
                )
                if not ok:
                    if not dispatched:
                        # 首台即失败 → 整体 outbox，不谎报成功
                        outbox = _write_outbox(
                            {
                                **req,
                                "para_payload": payload,
                                "para_response": _summarize_para_response(body),
                            }
                        )
                        err_text = str(
                            (body.get("error") or body.get("detail") or resp.text[:500])
                            if isinstance(body, dict)
                            else resp.text[:500]
                        )
                        return {
                            "handler": "para_delegate",
                            "ok": False,
                            "queued": True,
                            "status": "para_api_rejected_outboxed",
                            "status_code": resp.status_code,
                            "source": "para_api",
                            "failure_kind": "para_api",
                            "para_tier": tier,
                            "error": err_text,
                            "outbox_path": str(outbox),
                            "request": _public_request(req),
                            "response": _summarize_para_response(body),
                            "devices": [
                                {
                                    "device_id": device_id,
                                    "device_name": device.get("name"),
                                    "tool_name": selected_tool or _dev_tool(),
                                }
                            ],
                        }
                    continue  # 多设备时后续设备失败：记录并继续，task 已建
                accepted = _summarize_para_response(body)
                if not task_id:
                    task_id = str(accepted.get("task_id") or "").strip()
                _force_single_device_attempt(
                    {**req, "device_id": device_id, "report_only": report_only}, accepted
                )
                dispatched.append(
                    {
                        "device_id": device_id,
                        "device_name": accepted.get("device_name") or device.get("name"),
                        "subtask_id": accepted.get("subtask_id"),
                        "tool_name": selected_tool or _dev_tool(),
                    }
                )

            if not dispatched:
                return _outbox_response(
                    {**req, "para_payload": first_payload},
                    status="para_api_no_subtask_created",
                    error="Para API 未创建任何 subtask",
                )

            should_wait = _coerce_bool(req.get("wait_for_para"), _wait_for_completion_default())
            device_scope = "local_device" if tier == 1 else "all_devices"
            if should_wait:
                if not task_id:
                    return {
                        "handler": "para_delegate",
                        "ok": False,
                        "accepted": True,
                        "status": "para_api_missing_task_id",
                        "source": "para_api",
                        "para_tier": tier,
                        "device_scope": device_scope,
                        "request": _public_request(req),
                        "devices": dispatched,
                        "error": "Para API accepted but response missing task.id",
                    }
                final = _wait_for_para_task(client, base, token, task_id, req)
                return {
                    "handler": "para_delegate",
                    "ok": bool(final.get("ok")),
                    "accepted": True,
                    "completed": bool(final.get("ok")),
                    "status": final.get("status"),
                    "source": "para_api",
                    "auth": token_info["source"],
                    "para_tier": tier,
                    "device_scope": device_scope,
                    "request": _public_request(req),
                    "devices": dispatched,
                    "para_result": final.get("snapshot"),
                    "error": (
                        "" if final.get("ok") else str(final.get("error") or "Para task failed")
                    ),
                }
            return {
                "handler": "para_delegate",
                "ok": True,
                "accepted": True,
                "completed": False,
                "status": "para_task_accepted",
                "source": "para_api",
                "auth": token_info["source"],
                "para_tier": tier,
                "device_scope": device_scope,
                "request": _public_request(req),
                "devices": dispatched,
            }
    except Exception as exc:  # noqa: BLE001
        return _outbox_response(
            {**req, "para_payload": first_payload},
            status="para_api_failed_outboxed",
            error=f"Para API 调用失败，已写入 outbox: {str(exc)[:500]}",
        )


def _coerce_bool(value: Any, default: bool) -> bool:
    if value is None or value == "":
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    s = str(value).strip().lower()
    if s in {"1", "true", "yes", "on"}:
        return True
    if s in {"0", "false", "no", "off"}:
        return False
    return default


def _post_webhook(req: Dict[str, Any]) -> Dict[str, Any]:
    url = _webhook_url()
    if not url:
        return _post_para_api(req)
    try:
        resp = httpx.post(
            url,
            json=req,
            timeout=float(os.environ.get("MODSTORE_PARA_WEBHOOK_TIMEOUT_SEC", "60")),
            trust_env=False,
        )
        body: Any = {}
        try:
            body = resp.json() if resp.content else {}
        except Exception:
            body = {"raw": resp.text[:4000]}
        ok = resp.status_code < 400 and bool(body.get("ok", resp.status_code < 300))
        return {
            "handler": "para_delegate",
            "ok": ok,
            "status_code": resp.status_code,
            "source": "para_webhook",
            "response": body,
            "request": _public_request(req),
            "error": "" if ok else str(body.get("error") or body.get("detail") or resp.text[:500]),
        }
    except Exception as exc:  # noqa: BLE001
        return _outbox_response(
            req,
            status="webhook_failed_outboxed",
            error=f"Para webhook 调用失败，已写入 outbox: {str(exc)[:500]}",
        )


def dispatch_para_delegate(
    *,
    task: str,
    input_data: Optional[Dict[str, Any]] = None,
    employee_id: str,
) -> Dict[str, Any]:
    if not para_delegate_enabled():
        return {
            "handler": "para_delegate",
            "ok": False,
            "error": "MODSTORE_PARA_DELEGATE_ENABLED=0",
        }
    req = _build_request(task=task, input_data=dict(input_data or {}), employee_id=employee_id)
    return _post_webhook(req)


__all__ = ["dispatch_para_delegate", "para_delegate_enabled", "para_delegate_ready_for_dispatch"]
