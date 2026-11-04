"""Para task state, device recovery and merge request transport."""

from __future__ import annotations

import os
import time
from datetime import timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx

from modstore_server.operational_errors import RECOVERABLE_ERRORS

from . import config, para_auth, workspace


def _fetch_para_task_report_excerpt(
    task_id: Optional[str],
    subtask_id: Optional[str],
    limit: int = 8000,
) -> str:
    if not task_id:
        return ""
    api_base = os.environ.get("MODSTORE_PARA_API_BASE", "").strip()
    if not api_base:
        return ""
    try:
        headers = para_auth._guest_auth_headers(api_base)
        with httpx.Client(
            timeout=20.0, trust_env=False, verify=para_auth._para_tls_verify()
        ) as client:
            resp = client.get(f"{api_base.rstrip('/')}/api/tasks/{task_id}", headers=headers)
            resp.raise_for_status()
            task = (resp.json() or {}).get("task") or {}
    except RECOVERABLE_ERRORS:
        config.logger.warning("failed to fetch Para task report logs")
        return ""
    chunks: List[str] = []
    for subtask in task.get("subTasks") or task.get("subtasks") or []:
        if subtask_id and str(subtask.get("id")) != str(subtask_id):
            continue
        for log in subtask.get("logs") or []:
            content = str(log.get("content") or "").strip()
            if content:
                chunks.append(content)
    return "\n".join(chunks)[-limit:]


def _fetch_para_task_state(api_base: str, task_id: str) -> Dict[str, Any]:
    headers = para_auth._guest_auth_headers(api_base)
    with httpx.Client(timeout=20.0, trust_env=False, verify=para_auth._para_tls_verify()) as client:
        resp = client.get(f"{api_base.rstrip('/')}/api/tasks/{task_id}", headers=headers)
        resp.raise_for_status()
        task = (resp.json() or {}).get("task") or {}
    return task if isinstance(task, dict) else {}


def _kickstart_para_agent() -> Dict[str, Any]:
    if not config._env_bool("MODSTORE_SELF_MAINTENANCE_KICKSTART_PARA_AGENT", True):
        return {"attempted": False, "reason": "disabled"}
    import sys

    if sys.platform != "darwin":
        return {
            "attempted": False,
            "reason": f"platform {sys.platform} not supported (launchctl is macOS only)",
        }
    label = os.environ.get(
        "MODSTORE_PARA_AGENT_LAUNCHD_LABEL", "com.xcmax.para-main-agent.watchdog"
    )
    target = f"gui/{os.getuid()}/{label}"
    domain = f"gui/{os.getuid()}"
    plist = Path(
        os.environ.get("MODSTORE_PARA_AGENT_LAUNCHD_PLIST")
        or str(Path.home() / "Library/LaunchAgents" / f"{label}.plist")
    )
    try:
        output = workspace._run_cmd(["launchctl", "kickstart", "-k", target], timeout=30)
        return {"attempted": True, "ok": True, "output": output, "target": target}
    except RECOVERABLE_ERRORS as first_exc:
        bootstrap_result: Dict[str, Any] = {"attempted": False}
        if plist.exists():
            try:
                bootstrap_output = workspace._run_cmd(
                    ["launchctl", "bootstrap", domain, str(plist)], timeout=30
                )
                bootstrap_result = {
                    "attempted": True,
                    "ok": True,
                    "output": bootstrap_output,
                    "plist": str(plist),
                }
            except RECOVERABLE_ERRORS as bootstrap_exc:
                bootstrap_text = str(bootstrap_exc)
                bootstrap_result = {
                    "attempted": True,
                    "error": bootstrap_text,
                    "ok": "already bootstrapped" in bootstrap_text.lower(),
                    "plist": str(plist),
                }
        try:
            output = workspace._run_cmd(["launchctl", "kickstart", "-k", target], timeout=30)
            return {
                "attempted": True,
                "bootstrap": bootstrap_result,
                "ok": True,
                "output": output,
                "target": target,
            }
        except RECOVERABLE_ERRORS as second_exc:
            config.logger.warning(
                "failed to bootstrap/kickstart Para agent first_error_type=%s second_error_type=%s",
                type(first_exc).__name__,
                type(second_exc).__name__,
            )
            return {
                "attempted": True,
                "bootstrap": bootstrap_result,
                "error": str(second_exc),
                "first_error": str(first_exc),
                "ok": False,
                "target": target,
            }


def _clear_stale_para_current_task(*, device_id: str, current_task: str) -> Dict[str, Any]:
    db_file = para_auth._para_db_file()
    if db_file is None:
        return {"cleared": False, "reason": "para_db_file_missing"}
    try:
        import sqlite3

        with sqlite3.connect(str(db_file)) as conn:
            cur = conn.execute(
                "update tool_statuses set current_task=NULL, status='idle' where device_id=? and tool_name='codex' and current_task=?",
                (device_id, current_task),
            )
            if cur.rowcount <= 0:
                cur = conn.execute(
                    "update tool_statuses set current_task=NULL, status='idle' where device_id=? and tool_name='codex' and status='idle' and current_task is not null and current_task <> ''",
                    (device_id,),
                )
            conn.commit()
        return {"cleared": cur.rowcount > 0, "db_file": str(db_file)}
    except RECOVERABLE_ERRORS as exc:
        config.logger.exception("failed to clear stale para current_task")
        return {"cleared": False, "error": str(exc), "db_file": str(db_file)}


def _reconcile_orphan_para_running_tasks(*, device_id: str) -> Dict[str, Any]:
    db_file = para_auth._para_db_file()
    if db_file is None:
        return {"reconciled": False, "reason": "para_db_file_missing"}
    ttl_sec = max(30, config._env_int("MODSTORE_PARA_ORPHAN_RUNNING_TASK_TTL_SEC", 300))
    now = config._utc_now()
    cutoff = now - timedelta(seconds=ttl_sec)
    now_text = now.isoformat(timespec="milliseconds").replace("+00:00", "Z")
    cutoff_text = cutoff.isoformat(timespec="milliseconds").replace("+00:00", "Z")
    try:
        import sqlite3

        with sqlite3.connect(str(db_file)) as conn:
            rows = conn.execute(
                "\n                select id, task_id\n                from sub_tasks\n                where device_id=?\n                  and tool_name='codex'\n                  and status='running'\n                  and coalesce(updated_at, created_at, '') < ?\n                ",
                (device_id, cutoff_text),
            ).fetchall()
            task_ids = sorted({str(row[1]) for row in rows if row and row[1]})
            if rows:
                conn.executemany(
                    "\n                    update sub_tasks\n                    set status='failed',\n                        completed_at=?,\n                        updated_at=?,\n                        last_error=coalesce(last_error, 'orphan running task reclaimed because codex tool is idle')\n                    where id=?\n                    ",
                    [(now_text, now_text, str(row[0])) for row in rows],
                )
                for task_id in task_ids:
                    remaining = conn.execute(
                        "select count(*) from sub_tasks where task_id=? and status='running'",
                        (task_id,),
                    ).fetchone()
                    if int((remaining or [0])[0] or 0) <= 0:
                        conn.execute(
                            "update tasks set status='failed', completed_at=? where id=? and status='running'",
                            (now_text, task_id),
                        )
            conn.commit()
        return {
            "db_file": str(db_file),
            "reconciled": bool(rows),
            "subtask_count": len(rows),
            "task_ids": task_ids,
            "ttl_sec": ttl_sec,
        }
    except RECOVERABLE_ERRORS as exc:
        config.logger.exception("failed to reconcile orphan Para running tasks")
        return {"reconciled": False, "error": str(exc), "db_file": str(db_file)}


def _wait_for_para_device_online() -> Dict[str, Any]:
    api_base = os.environ.get("MODSTORE_PARA_API_BASE", "").strip()
    device_id = os.environ.get("MODSTORE_PARA_DEVICE_ID", "").strip()
    if not api_base or not device_id:
        return {"online": False, "reason": "missing_para_api_base_or_device_id"}
    timeout_sec = max(0, config._env_int("MODSTORE_SELF_MAINTENANCE_DEVICE_ONLINE_WAIT_SEC", 60))
    poll_sec = max(1, config._env_int("MODSTORE_SELF_MAINTENANCE_DEVICE_ONLINE_POLL_SEC", 5))
    deadline = time.monotonic() + timeout_sec
    last_status: Dict[str, Any] = {}
    last_error = ""
    headers: Optional[Dict[str, str]] = None
    kickstart_result: Optional[Dict[str, Any]] = None
    while True:
        try:
            if headers is None:
                headers = para_auth._guest_auth_headers(api_base)
            with httpx.Client(
                timeout=15.0, trust_env=False, verify=para_auth._para_tls_verify()
            ) as client:
                resp = client.get(f"{api_base.rstrip('/')}/api/devices", headers=headers)
                if resp.status_code in {401, 403}:
                    headers = None
                    para_auth._PARA_GUEST_AUTH_CACHE.pop(api_base.rstrip("/"), None)
                    raise RuntimeError(f"device status auth failed: {resp.status_code}")
                resp.raise_for_status()
                payload = resp.json() or {}
            devices = payload.get("devices") if isinstance(payload, dict) else payload
            if not isinstance(devices, list):
                devices = []
            target = None
            for item in devices:
                if isinstance(item, dict) and str(item.get("id") or "") == device_id:
                    target = item
                    break
            if target is None:
                last_status = {"reason": "device_not_found", "device_id": device_id}
            else:
                status = str(target.get("status") or "").lower()
                online = bool(target.get("online")) or status == "online"
                codex_tool = {}
                tools = target.get("tools")
                if isinstance(tools, list):
                    for tool in tools:
                        if isinstance(tool, dict) and str(tool.get("toolName") or "") == "codex":
                            codex_tool = tool
                            break
                tool_status = str(codex_tool.get("status") or "").lower()
                current_task = str(codex_tool.get("currentTask") or "").strip()
                stale_clear: Optional[Dict[str, Any]] = None
                if online and current_task and (tool_status in {"", "idle"}):
                    stale_clear = _clear_stale_para_current_task(
                        device_id=device_id, current_task=current_task
                    )
                    if stale_clear.get("cleared"):
                        last_status = {
                            "codex_tool": codex_tool,
                            "device_id": device_id,
                            "name": target.get("name"),
                            "online": online,
                            "stale_clear": stale_clear,
                            "status": target.get("status"),
                        }
                        return {
                            **last_status,
                            "reason": "online_after_stale_current_task_clear",
                        }
                if online and current_task:
                    last_status = {
                        "codex_tool": codex_tool,
                        "device_id": device_id,
                        "name": target.get("name"),
                        "online": True,
                        "busy": True,
                        "stale_clear": stale_clear,
                        "status": target.get("status"),
                    }
                    if config._env_bool("MODSTORE_SELF_MAINTENANCE_ALLOW_BUSY_DEVICE", False):
                        return {**last_status, "reason": "online_busy_allowed"}
                    if kickstart_result is None:
                        kickstart_result = _kickstart_para_agent()
                        headers = None
                else:
                    orphan_reconcile: Optional[Dict[str, Any]] = None
                    if online and (not current_task) and (tool_status in {"", "idle"}):
                        orphan_reconcile = _reconcile_orphan_para_running_tasks(device_id=device_id)
                    last_status = {
                        "codex_tool": codex_tool,
                        "device_id": device_id,
                        "name": target.get("name"),
                        "online": online,
                        "orphan_reconcile": orphan_reconcile,
                        "status": target.get("status"),
                    }
                    if online:
                        return {**last_status, "reason": "online"}
                    if kickstart_result is None:
                        kickstart_result = _kickstart_para_agent()
                        headers = None
        except RECOVERABLE_ERRORS as exc:
            last_error = str(exc)
            if kickstart_result is None:
                kickstart_result = _kickstart_para_agent()
                headers = None
        if time.monotonic() >= deadline:
            was_online = bool(last_status.get("online")) or bool(last_status.get("busy"))
            return {
                **last_status,
                "error": last_error,
                "kickstart": kickstart_result,
                "online": was_online,
                "reason": (
                    "device_busy_wait_timeout"
                    if last_status.get("busy")
                    else "device_online_wait_timeout"
                ),
                "timeout_sec": timeout_sec,
            }
        time.sleep(poll_sec)


def _mark_para_task_merged(*, api_base: str, task_id: str, merge_sha: str) -> Dict[str, Any]:
    headers = para_auth._guest_auth_headers(api_base)
    with httpx.Client(timeout=30.0, trust_env=False, verify=para_auth._para_tls_verify()) as client:
        resp = client.post(
            f"{api_base.rstrip('/')}/api/tasks/{task_id}/merge",
            headers=headers,
            json={"merge_commit_sha": merge_sha},
        )
        resp.raise_for_status()
        payload = resp.json()
        if not isinstance(payload, dict):
            raise ValueError("Para merge response must be a JSON object")
        return payload


def _request_para_task_merge(*, api_base: str, task_id: str) -> Dict[str, Any]:
    """Queue the already-pushed Para workspace only after loop gates pass.

    The CVM cannot reach GitHub directly, while the Para worker on the Mac can.
    Keeping this request here makes review, QA and ``autonomy_guard`` the sole
    authorization path; the device agent only prepares and pushes the branch.
    """
    workspace_root = (
        os.environ.get("MODSTORE_PARA_WORKSPACE_ROOT")
        or "/Users/a4243342/XCMAX-runtime/para-main-agent/workspace"
    ).strip()
    workspace_path = str(Path(workspace_root).expanduser() / task_id)
    headers = para_auth._guest_auth_headers(api_base)
    with httpx.Client(timeout=30.0, trust_env=False, verify=para_auth._para_tls_verify()) as client:
        resp = client.post(
            f"{api_base.rstrip('/')}/api/tasks/{task_id}/request-merge",
            headers=headers,
            json={"workspace_path": workspace_path, "auto_merge": True},
        )
        resp.raise_for_status()
        payload = resp.json()
    return {
        "ok": True,
        "para_response": payload,
        "reason": "merge_requested_after_loop_risk_gate",
        "workspace_path": workspace_path,
    }
