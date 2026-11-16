"""Authenticated admin maintenance surface; executor credentials stay server-side."""

from __future__ import annotations

import json
import os
from pathlib import Path
from uuid import UUID

import requests

from app.application.autonomy import approval_resume as approvals
from app.domain.autonomy.audit_log import append_autonomy_audit
from scripts.autonomy.autonomy_types import Action, ActionType
from scripts.autonomy.rundeck_executor import execute

LABELS = {"restart_service": "重启服务", "clear_logs": "清理过期日志"}
EXECUTOR = "rundeck_maintenance"


def bindings():
    raw = json.loads(os.environ.get("XCAGI_RUNDECK_JOBS", "{}"))
    return {key: str(UUID(value)) for key, value in raw.items() if key in LABELS}


def receipt_dir():
    root = os.environ.get("XCAGI_AUTONOMY_DATA_DIR")
    if not root:
        raise ValueError("维护任务数据目录尚未配置")
    return str(Path(root) / "maintenance")


def api(method, path):
    from urllib.parse import urlsplit

    base = os.environ.get("XCAGI_RUNDECK_URL", "").rstrip("/")
    parsed = urlsplit(base)
    if (
        parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
        or not (
            parsed.scheme == "https"
            or parsed.scheme == "http"
            and parsed.hostname in {"localhost", "127.0.0.1"}
        )
    ):
        raise ValueError("维护执行服务地址尚未正确配置")
    with requests.Session() as session:
        session.trust_env = False
        response = session.request(
            method,
            f"{base}/api/45/{path}",
            headers={
                "X-Rundeck-Auth-Token": os.environ["XCAGI_RUNDECK_TOKEN"],
                "Accept": "application/json",
            },
            timeout=10,
            allow_redirects=False,
        )
        if not 200 <= response.status_code < 300:
            raise ValueError(f"维护执行服务返回错误（{response.status_code}）")
        return response.json()


def perform(payload):
    kind = payload["kind"]
    # Approval is tied to the exact job binding; configuration changes require a new request.
    if bindings().get(kind) != payload["job_id"]:
        raise ValueError("维护任务配置已变化，请重新申请")
    result = execute(Action(ActionType(kind), idempotency_key=payload["request_id"]), receipt_dir())
    return {"ok": result.ok, "detail": result.detail, "recovery": "unverified"}


def register():
    approvals.register_action_executor(EXECUTOR, perform)


def snapshot():
    configured = bindings()
    rows = []
    for kind, job in configured.items():
        data = api("GET", f"job/{job}/executions?max=20")
        for item in data.get("executions", []):
            rows.append(
                {
                    "id": str(item["id"]),
                    "action": kind,
                    "label": LABELS[kind],
                    "status": item.get("status", "unknown"),
                    "started_at": (item.get("date-started") or {}).get("date"),
                    "ended_at": (item.get("date-ended") or {}).get("date"),
                    "recovery": "unverified",
                }
            )
    from app.application.autonomy.approval_center import _latest_actions

    pending = [
        {
            "action_id": item["action_id"],
            "action": item["action"],
            "label": LABELS.get(item["action"], item["action"]),
            "state": item["state"],
        }
        for item in _latest_actions()
        if item.get("executor_name") == EXECUTOR
        and item.get("state") in {"pending_approval", "approval_requested"}
    ]
    return {
        "connected": bool(configured),
        "environment": os.environ.get("XCAGI_MAINTENANCE_ENVIRONMENT", "未标明环境"),
        "tasks": [{"action": key, "label": LABELS[key]} for key in configured],
        "executions": sorted(rows, key=lambda x: int(x["id"]), reverse=True)[:40],
        "pending": pending,
    }


def request_run(kind, request_id, actor):
    register()
    configured = bindings()
    if kind not in configured:
        raise ValueError("该维护任务尚未配置")
    request_id = str(UUID(request_id))
    action_id = f"maintenance:{request_id}"
    existing = approvals.get_action_state(action_id)
    if existing:
        if existing.get("action") != kind:
            raise ValueError("请求编号已用于其他动作")
        return {"state": existing["state"], "action_id": action_id}
    payload = {"kind": kind, "request_id": request_id, "job_id": configured[kind], "actor": actor}
    decision, pending = approvals.request_action(
        kind,
        payload=payload,
        action_id=action_id,
        source="admin_maintenance",
        executor_name=EXECUTOR,
    )
    if pending:
        return {"state": pending["state"], "action_id": action_id}
    if not decision.allowed:
        raise ValueError("风险门禁未允许该维护动作，请查看自治审计")
    result = perform(payload)
    append_autonomy_audit(
        {
            "action_id": action_id,
            "action": kind,
            "actor": actor,
            "source": "admin_maintenance",
            "decision": "executed" if result["ok"] else "execution_failed",
            "outcome": result,
        }
    )
    return {
        "state": "executed" if result["ok"] else "execution_failed",
        "result": result,
        "action_id": action_id,
    }


def execution_detail(execution_id):
    execution_id = str(int(execution_id))
    item = api("GET", f"execution/{execution_id}")
    if str(item.get("job", {}).get("id")) not in bindings().values():
        raise ValueError("该执行记录不属于已授权维护任务")
    return item


def cancel(execution_id, actor):
    item = execution_detail(execution_id)
    if item.get("status") not in {"running", "scheduled"}:
        raise ValueError("任务已结束，不能取消")
    result = api("POST", f"execution/{int(execution_id)}/abort")
    append_autonomy_audit(
        {
            "action": "cancel_maintenance",
            "actor": actor,
            "action_id": f"maintenance-execution:{int(execution_id)}",
            "source": "admin_maintenance",
            "decision": "cancel_requested",
        }
    )
    return {
        "state": "cancel_requested",
        "confirmed": result.get("abort", {}).get("status") == "aborted",
    }
