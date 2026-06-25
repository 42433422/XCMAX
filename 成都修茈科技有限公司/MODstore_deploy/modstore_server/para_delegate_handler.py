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


def _env_bool(name: str, default: str = "0") -> bool:
    return os.environ.get(name, default).strip().lower() in ("1", "true", "yes", "on")


def para_delegate_enabled() -> bool:
    return _env_bool("MODSTORE_PARA_DELEGATE_ENABLED", "1")


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
        raw = os.environ.get("MODSTORE_PARA_WAIT_TIMEOUT_SEC") or "900"
    try:
        return max(5.0, float(raw))
    except (TypeError, ValueError):
        return 900.0


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
        / f"{req.get('created_at','').replace(':', '').replace('+', 'Z')}-{req['request_id']}.json"
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


def _dev_tool() -> str:
    """loops 桥默认派给的设备工具(DevFleet devTool)，用于设备过滤。"""
    return (os.environ.get("MODSTORE_PARA_DEV_TOOL") or "codex").strip() or "codex"


def _device_discovery_enabled() -> bool:
    return _env_bool("MODSTORE_PARA_DEVICE_DISCOVERY", "1")


def _safe_json(resp: httpx.Response) -> Any:
    try:
        return resp.json() if resp.content else {}
    except Exception:
        return {"raw": resp.text[:4000]}


def _device_tool_entry(item: Dict[str, Any], tool_name: str) -> Optional[Dict[str, Any]]:
    tools = item.get("tools")
    if isinstance(tools, list):
        for tool in tools:
            if isinstance(tool, dict) and tool.get("toolName") == tool_name:
                return tool
    return None


def _device_eligible(item: Any, tool_name: str) -> bool:
    """设备能否承接派工：在线 + 目标工具已装且非占用 + 具备能力。与 FHD 同构。"""
    if not isinstance(item, dict):
        return False
    if str(item.get("status") or "") != "online":
        return False
    tool = _device_tool_entry(item, tool_name)
    if tool and str(tool.get("status") or "") == "not_installed":
        return False
    if tool and str(tool.get("status") or "") == "running" and tool.get("currentTask"):
        return False
    if not tool:
        caps = item.get("capabilities") if isinstance(item.get("capabilities"), dict) else {}
        if caps.get(f"{tool_name}_cli") is True:
            return True
        return str(item.get("devTool") or "") == tool_name
    return True


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
        return 1, [{"id": explicit}], ""
    if not _device_discovery_enabled():
        return (
            1,
            [],
            "未配置 MODSTORE_PARA_DEVICE_ID 且设备发现关闭(MODSTORE_PARA_DEVICE_DISCOVERY=0)",
        )
    tool = _dev_tool()
    devices = _fetch_devices(client, base, token)
    tier = _resolve_tier(req)
    if tier == 1:
        local = _select_local_device(devices, tool)
        if local:
            return 1, local, ""
        tier = 2  # 本机不可用 → 升二级
    selected = _select_fleet_devices(devices, req, tool)
    if not selected:
        return tier, [], f"未发现在线可用 {tool} 设备(共 {len(devices)} 台)"
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


def _post_para_api(req: Dict[str, Any]) -> Dict[str, Any]:
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

    base_prompt = _build_para_prompt(req)
    first_payload: Dict[str, Any] = {}
    try:
        with httpx.Client(timeout=_api_timeout(), trust_env=False) as client:
            token_info = _get_para_token(client, base)
            token = token_info["token"]

            tier, sel_devices, select_reason = _resolve_dispatch_devices(client, base, token, req)
            if not sel_devices:
                return _outbox_response(
                    req,
                    status="blocked_no_online_para_device",
                    error=select_reason or "未发现在线可用 Para 工作设备",
                    queued=False,
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
                    "branch": str(req.get("branch") or "main").strip() or "main",
                    "subtask_title": _para_subtask_title(req, index, total),
                    "report_only": bool(req.get("report_only")),
                    "max_attempts": 1,
                }
                if repo_url:
                    payload["repo_url"] = repo_url
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
                        return {
                            "handler": "para_delegate",
                            "ok": False,
                            "queued": True,
                            "status": "para_api_rejected_outboxed",
                            "status_code": resp.status_code,
                            "source": "para_api",
                            "para_tier": tier,
                            "error": str(
                                (body.get("error") or body.get("detail") or resp.text[:500])
                                if isinstance(body, dict)
                                else resp.text[:500]
                            ),
                            "outbox_path": str(outbox),
                            "request": _public_request(req),
                            "response": _summarize_para_response(body),
                        }
                    continue  # 多设备时后续设备失败：记录并继续，task 已建
                accepted = _summarize_para_response(body)
                if not task_id:
                    task_id = str(accepted.get("task_id") or "").strip()
                _force_single_device_attempt({**req, "device_id": device_id}, accepted)
                dispatched.append(
                    {
                        "device_id": device_id,
                        "device_name": accepted.get("device_name") or device.get("name"),
                        "subtask_id": accepted.get("subtask_id"),
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


__all__ = ["dispatch_para_delegate", "para_delegate_enabled"]
