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
    branch = str(
        input_data.get("branch")
        or input_data.get("base_branch")
        or os.environ.get("MODSTORE_PARA_BRANCH")
        or "main"
    ).strip() or "main"
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
        "repo_url": str(input_data.get("repo_url") or os.environ.get("MODSTORE_PARA_REPO_URL") or ""),
        "branch": branch,
        "device_id": str(input_data.get("device_id") or os.environ.get("MODSTORE_PARA_DEVICE_ID") or ""),
        "depends_on": input_data.get("depends_on") if isinstance(input_data.get("depends_on"), list) else [],
        "para_task_id": str(input_data.get("para_task_id") or input_data.get("task_id") or ""),
        "dispatch_line": str(input_data.get("dispatch_line") or ""),
        "priority": str(input_data.get("priority") or ""),
        "action_item_id": input_data.get("action_item_id"),
        "record_id": input_data.get("record_id"),
        "wait_for_para": input_data.get("wait_for_para"),
        "wait_timeout_sec": input_data.get("wait_timeout_sec"),
        "evidence": input_data.get("evidence") if isinstance(input_data.get("evidence"), dict) else {},
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
    out = _outbox_dir() / f"{req.get('created_at','').replace(':', '').replace('+', 'Z')}-{req['request_id']}.json"
    out.write_text(json.dumps(req, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return out


def _outbox_response(req: Dict[str, Any], *, status: str, error: str, queued: bool = True) -> Dict[str, Any]:
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
        os.environ.get("MODSTORE_PARA_AUTH_TOKEN")
        or os.environ.get("DEVFLEET_AUTH_TOKEN")
        or ""
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
        task = body.get("task") if isinstance(body, dict) and isinstance(body.get("task"), dict) else {}
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


def _post_para_api(req: Dict[str, Any]) -> Dict[str, Any]:
    base = _api_base()
    if not base:
        return _outbox_response(
            req,
            status="awaiting_para_dispatcher",
            error="MODSTORE_PARA_API_BASE 未配置；已写入 outbox，但未真实派发到 Para",
        )

    if not str(req.get("device_id") or "").strip():
        return _outbox_response(
            req,
            status="blocked_missing_para_device",
            error="MODSTORE_PARA_DEVICE_ID/input device_id 未配置，无法选择 Para 工作设备",
            queued=False,
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

    payload: Dict[str, Any] = {
        "device_id": str(req.get("device_id") or "").strip(),
        "title": str(req.get("title") or "MODstore loop task").strip(),
        "prompt": _build_para_prompt(req),
        "branch": str(req.get("branch") or "main").strip() or "main",
        "subtask_title": f"{req.get('mode') or 'code'}: {req.get('title') or 'MODstore loop task'}"[:240],
        "report_only": bool(req.get("report_only")),
    }
    if repo_url:
        payload["repo_url"] = repo_url
    if req.get("para_task_id"):
        payload["task_id"] = str(req.get("para_task_id") or "").strip()
    if isinstance(req.get("depends_on"), list) and req.get("depends_on"):
        payload["depends_on"] = req.get("depends_on")
    payload["max_attempts"] = 1

    try:
        with httpx.Client(timeout=_api_timeout(), trust_env=False) as client:
            token_info = _get_para_token(client, base)
            resp = client.post(
                f"{base}/api/tasks",
                headers={"Authorization": f"Bearer {token_info['token']}"},
                json=payload,
            )
            body: Any = {}
            try:
                body = resp.json() if resp.content else {}
            except Exception:
                body = {"raw": resp.text[:4000]}
            ok = resp.status_code < 400 and isinstance(body, dict) and bool(body.get("task") or body.get("subtask"))
            if not ok:
                outbox = _write_outbox({**req, "para_payload": payload, "para_response": _summarize_para_response(body)})
                return {
                    "handler": "para_delegate",
                    "ok": False,
                    "queued": True,
                    "status": "para_api_rejected_outboxed",
                    "status_code": resp.status_code,
                    "source": "para_api",
                    "error": str(
                        (body.get("error") or body.get("detail") or resp.text[:500])
                        if isinstance(body, dict)
                        else resp.text[:500]
                    ),
                    "outbox_path": str(outbox),
                    "request": _public_request(req),
                    "response": _summarize_para_response(body),
                }
            accepted = _summarize_para_response(body)
            auto_retry = _force_single_device_attempt(req, accepted)
            task_id = str(accepted.get("task_id") or "").strip()
            should_wait = _coerce_bool(req.get("wait_for_para"), _wait_for_completion_default())
            if should_wait:
                if not task_id:
                    return {
                        "handler": "para_delegate",
                        "ok": False,
                        "accepted": True,
                        "status": "para_api_missing_task_id",
                        "source": "para_api",
                    "request": _public_request(req),
                    "response": accepted,
                    "auto_retry": auto_retry,
                    "error": "Para API accepted but response missing task.id",
                }
                final = _wait_for_para_task(client, base, token_info["token"], task_id, req)
                return {
                    "handler": "para_delegate",
                    "ok": bool(final.get("ok")),
                    "accepted": True,
                    "completed": bool(final.get("ok")),
                    "status_code": resp.status_code,
                    "status": final.get("status"),
                    "source": "para_api",
                    "auth": token_info["source"],
                    "request": _public_request(req),
                    "response": accepted,
                    "auto_retry": auto_retry,
                    "para_result": final.get("snapshot"),
                    "error": "" if final.get("ok") else str(final.get("error") or "Para task failed"),
                }
            return {
                "handler": "para_delegate",
                "ok": True,
                "accepted": True,
                "completed": False,
                "status_code": resp.status_code,
                "status": "para_task_accepted",
                "source": "para_api",
                "auth": token_info["source"],
                "request": _public_request(req),
                "response": accepted,
                "auto_retry": auto_retry,
            }
    except Exception as exc:  # noqa: BLE001
        return _outbox_response(
            {**req, "para_payload": payload},
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
