# mypy: disable-error-code="valid-type, attr-defined, no-any-return"
"""Implementation extracted from the public facade module."""

from __future__ import annotations

import importlib

from modstore_server.operational_errors import RECOVERABLE_ERRORS


def _facade():
    return importlib.import_module("modstore_server.para_delegate_handler")


def _post_para_api_once(
    req: _facade().Dict[str, _facade().Any],
) -> _facade().Dict[str, _facade().Any]:
    h = _facade()
    base = h._api_base()
    if not base:
        return h._outbox_response(
            req,
            status="awaiting_para_dispatcher",
            error="MODSTORE_PARA_API_BASE 未配置；已写入 outbox，但未真实派发到 Para",
        )
    repo_url = str(req.get("repo_url") or "").strip()
    if not repo_url and (not h._allow_local_workdir()):
        return h._outbox_response(
            req,
            status="blocked_missing_repo_url",
            error="缺少 repo_url；已拒绝让 Para 使用工作设备本地目录，避免污染设备工作区。请配置 MODSTORE_PARA_REPO_URL 或在任务输入里提供 repo_url；如确实要使用设备本地目录，显式设置 MODSTORE_PARA_ALLOW_LOCAL_WORKDIR=1。",
            queued=False,
        )
    branch = str(req.get("branch") or "main").strip() or "main"
    report_only = bool(req.get("report_only"))
    if repo_url and (not report_only) and (not h._allow_local_workdir()):
        git_check = h._git_preflight_branch(repo_url, branch)
        if not git_check.get("ok"):
            return h._outbox_response(
                req,
                status="blocked_git_preflight",
                error=str(git_check.get("error") or "git preflight failed"),
                queued=True,
            )
    base_prompt = h._build_para_prompt(req)
    first_payload: dict[str, object] = {}
    max_attempts = h._resolve_max_attempts(req)
    mode = str(req.get("mode") or "").strip().lower()
    auto_merge = bool(req.get("auto_merge"))
    if not auto_merge and mode in {"verify", "review", "report"} and (report_only is False):
        auto_merge = h._coerce_bool(req.get("auto_merge_on_complete"), False)
    workspace_path = str(
        req.get("workspace_path") or h.os.environ.get("MODSTORE_PARA_WORKSPACE_PATH") or ""
    ).strip()
    task_id = str(req.get("para_task_id") or "").strip()
    try:
        with h.httpx.Client(timeout=h._api_timeout(), trust_env=False) as client:
            token_info = h._get_para_token(client, base)
            token = token_info["token"]
            tier, sel_devices, select_reason = h._resolve_dispatch_devices(client, base, token, req)
            if not sel_devices:
                raw = req.get("raw_input") or {}
                if raw.get("_ticket_route") and not req.get("para_task_id"):
                    # No POST and no replayable outbox: this hop cannot still execute.
                    return {
                        "handler": "para_delegate",
                        "ok": False,
                        "accepted": False,
                        "queued": False,
                        "status": "blocked_no_online_para_device",
                        "error": select_reason or "No eligible Para device",
                        "request": h._public_request(req),
                    }
                return h._outbox_response(
                    req,
                    status="blocked_no_online_para_device",
                    error=select_reason or "未发现在线可用 Para 工作设备（executorReady）",
                    queued=True,
                )
            total = len(sel_devices)
            dispatched: list = []
            for index, device in enumerate(sel_devices):
                device_id = str(device.get("id") or "").strip()
                if not device_id:
                    continue
                payload: dict[str, object] = {
                    "device_id": device_id,
                    "title": str(req.get("title") or "MODstore loop task").strip(),
                    "prompt": h._multi_device_prompt(base_prompt, device, index, total),
                    "branch": branch,
                    "subtask_title": h._para_subtask_title(req, index, total),
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
                body = h._safe_json(resp)
                ok = (
                    resp.status_code < 400
                    and isinstance(body, dict)
                    and bool(body.get("task") or body.get("subtask"))
                )
                if not ok:
                    if not dispatched:
                        err_text = str(
                            body.get("error") or body.get("detail") or resp.text[:500]
                            if isinstance(body, dict)
                            else resp.text[:500]
                        )
                        response = h._summarize_para_response(body)
                        rejected = h._outbox_response(
                            {**req, "para_payload": payload, "para_response": response},
                            status="para_api_rejected_outboxed",
                            error=err_text,
                        )
                        return {
                            **rejected,
                            "status_code": resp.status_code,
                            "source": "para_api",
                            "failure_kind": "para_api",
                            "para_tier": tier,
                            "request": h._public_request(req),
                            "response": response,
                            "devices": [
                                {
                                    "device_id": device_id,
                                    "device_name": device.get("name"),
                                    "tool_name": selected_tool or h._dev_tool(),
                                }
                            ],
                        }
                    continue
                accepted = h._summarize_para_response(body)
                if not task_id:
                    task_id = str(accepted.get("task_id") or "").strip()
                h._force_single_device_attempt(
                    {**req, "device_id": device_id, "report_only": report_only},
                    accepted,
                )
                dispatched.append(
                    {
                        "device_id": device_id,
                        "device_name": accepted.get("device_name") or device.get("name"),
                        "subtask_id": accepted.get("subtask_id"),
                        "tool_name": selected_tool or h._dev_tool(),
                    }
                )
            if not dispatched:
                return h._outbox_response(
                    {**req, "para_payload": first_payload},
                    status="para_api_no_subtask_created",
                    error="Para API 未创建任何 subtask",
                )
            should_wait = h._coerce_bool(req.get("wait_for_para"), h._wait_for_completion_default())
            device_scope = "local_device" if tier == 1 else "all_devices"
            result = {
                "handler": "para_delegate",
                "ok": True,
                "accepted": True,
                "completed": False,
                "status": "para_task_accepted",
                "task_id": task_id,
                "source": "para_api",
                "auth": token_info["source"],
                "para_tier": tier,
                "device_scope": device_scope,
                "request": h._public_request(req),
                "devices": dispatched,
            }
            if not should_wait:
                return result
            if not task_id:
                return {
                    **result,
                    "ok": False,
                    "status": "para_api_missing_task_id",
                    "error": "Para API accepted but response missing task.id",
                }
            final = h._wait_for_para_task(client, base, token, task_id, req)
            return {
                **result,
                "ok": bool(final.get("ok")),
                "completed": bool(final.get("ok")),
                "status": final.get("status"),
                "para_result": final.get("snapshot"),
                "error": "" if final.get("ok") else str(final.get("error") or "Para task failed"),
            }
    except RECOVERABLE_ERRORS as exc:
        result = h._outbox_response(
            {**req, "para_task_id": task_id, "para_payload": first_payload},
            status="para_api_failed_outboxed",
            error=f"Para API 调用失败，已写入 outbox: {str(exc)[:500]}",
        )
        if task_id:
            result.update({"accepted": True, "task_id": task_id})
        return result


def _coerce_bool(value: _facade().Any, default: bool) -> bool:
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


def _post_webhook(
    req: _facade().Dict[str, _facade().Any],
) -> _facade().Dict[str, _facade().Any]:
    url = _facade()._webhook_url()
    if not url:
        raw = req.get("raw_input") if isinstance(req.get("raw_input"), dict) else {}
        hops = raw.get("_ticket_route") if isinstance(raw.get("_ticket_route"), list) else []
        if hops:
            return _facade()._post_ticket_route(req, hops)
        return _facade()._post_para_api(req)
    try:
        resp = _facade().httpx.post(
            url,
            json=req,
            timeout=float(_facade().os.environ.get("MODSTORE_PARA_WEBHOOK_TIMEOUT_SEC", "60")),
            trust_env=False,
        )
        body: _facade().Any = {}
        try:
            body = resp.json() if resp.content else {}
        except RECOVERABLE_ERRORS:
            body = {"raw": resp.text[:4000]}
        ok = resp.status_code < 400 and bool(body.get("ok", resp.status_code < 300))
        return {
            "handler": "para_delegate",
            "ok": ok,
            "status_code": resp.status_code,
            "source": "para_webhook",
            "response": body,
            "request": _facade()._public_request(req),
            "error": "" if ok else str(body.get("error") or body.get("detail") or resp.text[:500]),
        }
    except RECOVERABLE_ERRORS as exc:
        return _facade()._outbox_response(
            req,
            status="webhook_failed_outboxed",
            error=f"Para webhook 调用失败，已写入 outbox: {str(exc)[:500]}",
        )


def dispatch_para_delegate(
    *,
    task: str,
    input_data: _facade().Optional[_facade().Dict[str, _facade().Any]] = None,
    employee_id: str,
) -> _facade().Dict[str, _facade().Any]:
    if not _facade().para_delegate_enabled():
        return {
            "handler": "para_delegate",
            "ok": False,
            "error": "MODSTORE_PARA_DELEGATE_ENABLED=0",
        }
    if _facade().os.environ.get("MODSTORE_MAC_CONTROL_EMPLOYEE_DISPATCH") == "1":
        from modstore_server.mac_control_delegate import accept_employee

        return accept_employee(task, dict(input_data or {}), employee_id)
    req = _facade()._build_request(
        task=task, input_data=dict(input_data or {}), employee_id=employee_id
    )
    return _facade()._post_webhook(req)
