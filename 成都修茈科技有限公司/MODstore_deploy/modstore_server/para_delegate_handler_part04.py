# ruff: noqa
"""Implementation extracted from the public facade module."""
from __future__ import annotations
import importlib


def _facade():
    return importlib.import_module("modstore_server.para_delegate_handler")


def _post_para_api_once(
    req: _facade().Dict[str, _facade().Any]
) -> _facade().Dict[str, _facade().Any]:
    base = _facade()._api_base()
    if not base:
        return _facade()._outbox_response(
            req,
            status="awaiting_para_dispatcher",
            error="MODSTORE_PARA_API_BASE 未配置；已写入 outbox，但未真实派发到 Para",
        )
    repo_url = str(req.get("repo_url") or "").strip()
    if not repo_url and (not _facade()._allow_local_workdir()):
        return _facade()._outbox_response(
            req,
            status="blocked_missing_repo_url",
            error="缺少 repo_url；已拒绝让 Para 使用工作设备本地目录，避免污染设备工作区。请配置 MODSTORE_PARA_REPO_URL 或在任务输入里提供 repo_url；如确实要使用设备本地目录，显式设置 MODSTORE_PARA_ALLOW_LOCAL_WORKDIR=1。",
            queued=False,
        )
    branch = str(req.get("branch") or "main").strip() or "main"
    report_only = bool(req.get("report_only"))
    if repo_url and (not report_only) and (not _facade()._allow_local_workdir()):
        git_check = _facade()._git_preflight_branch(repo_url, branch)
        if not git_check.get("ok"):
            return _facade()._outbox_response(
                req,
                status="blocked_git_preflight",
                error=str(git_check.get("error") or "git preflight failed"),
                queued=True,
            )
    base_prompt = _facade()._build_para_prompt(req)
    first_payload: _facade().Dict[str, _facade().Any] = {}
    max_attempts = _facade()._resolve_max_attempts(req)
    mode = str(req.get("mode") or "").strip().lower()
    auto_merge = bool(req.get("auto_merge"))
    if not auto_merge and mode in {"verify", "review", "report"} and (report_only is False):
        auto_merge = _facade()._coerce_bool(req.get("auto_merge_on_complete"), False)
    workspace_path = str(
        req.get("workspace_path") or _facade().os.environ.get("MODSTORE_PARA_WORKSPACE_PATH") or ""
    ).strip()
    try:
        with _facade().httpx.Client(timeout=_facade()._api_timeout(), trust_env=False) as client:
            token_info = _facade()._get_para_token(client, base)
            token = token_info["token"]
            (tier, sel_devices, select_reason) = _facade()._resolve_dispatch_devices(
                client, base, token, req
            )
            if not sel_devices:
                return _facade()._outbox_response(
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
                payload: _facade().Dict[str, _facade().Any] = {
                    "device_id": device_id,
                    "title": str(req.get("title") or "MODstore loop task").strip(),
                    "prompt": _facade()._multi_device_prompt(base_prompt, device, index, total),
                    "branch": branch,
                    "subtask_title": _facade()._para_subtask_title(req, index, total),
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
                    f"{base}/api/tasks", headers={"Authorization": f"Bearer {token}"}, json=payload
                )
                body = _facade()._safe_json(resp)
                ok = (
                    resp.status_code < 400
                    and isinstance(body, dict)
                    and bool(body.get("task") or body.get("subtask"))
                )
                if not ok:
                    if not dispatched:
                        outbox = _facade()._write_outbox(
                            {
                                **req,
                                "para_payload": payload,
                                "para_response": _facade()._summarize_para_response(body),
                            }
                        )
                        err_text = str(
                            body.get("error") or body.get("detail") or resp.text[:500]
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
                            "request": _facade()._public_request(req),
                            "response": _facade()._summarize_para_response(body),
                            "devices": [
                                {
                                    "device_id": device_id,
                                    "device_name": device.get("name"),
                                    "tool_name": selected_tool or _facade()._dev_tool(),
                                }
                            ],
                        }
                    continue
                accepted = _facade()._summarize_para_response(body)
                if not task_id:
                    task_id = str(accepted.get("task_id") or "").strip()
                _facade()._force_single_device_attempt(
                    {**req, "device_id": device_id, "report_only": report_only}, accepted
                )
                dispatched.append(
                    {
                        "device_id": device_id,
                        "device_name": accepted.get("device_name") or device.get("name"),
                        "subtask_id": accepted.get("subtask_id"),
                        "tool_name": selected_tool or _facade()._dev_tool(),
                    }
                )
            if not dispatched:
                return _facade()._outbox_response(
                    {**req, "para_payload": first_payload},
                    status="para_api_no_subtask_created",
                    error="Para API 未创建任何 subtask",
                )
            should_wait = _facade()._coerce_bool(
                req.get("wait_for_para"), _facade()._wait_for_completion_default()
            )
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
                        "request": _facade()._public_request(req),
                        "devices": dispatched,
                        "error": "Para API accepted but response missing task.id",
                    }
                final = _facade()._wait_for_para_task(client, base, token, task_id, req)
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
                    "request": _facade()._public_request(req),
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
                "request": _facade()._public_request(req),
                "devices": dispatched,
            }
    except Exception as exc:
        return _facade()._outbox_response(
            {**req, "para_payload": first_payload},
            status="para_api_failed_outboxed",
            error=f"Para API 调用失败，已写入 outbox: {str(exc)[:500]}",
        )


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


def _post_webhook(req: _facade().Dict[str, _facade().Any]) -> _facade().Dict[str, _facade().Any]:
    url = _facade()._webhook_url()
    if not url:
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
        except Exception:
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
    except Exception as exc:
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
    req = _facade()._build_request(
        task=task, input_data=dict(input_data or {}), employee_id=employee_id
    )
    return _facade()._post_webhook(req)
