# mypy: disable-error-code="valid-type, attr-defined, no-any-return"
"""Implementation extracted from the public facade module."""

from __future__ import annotations

import importlib

from modstore_server.dot_ticket_dispatch import prepare_dolt_ticket_payload
from modstore_server.operational_errors import RECOVERABLE_ERRORS
from modstore_server.para_delegate_task_payloads import (
    PreparedTaskGroup,
    prepare_task_group,
    task_payload_options,
    validated_check_units,
)


def _facade():
    return importlib.import_module("modstore_server.para_delegate_handler")


def _attach_credential_grant(prompt: str, task_id: str) -> _facade().Any:
    """给派单任务签发短期凭据授权，把不含凭据值的授权引用附在提示词末尾。"""

    from modstore_server import cred_vault as credential_vault

    if not task_id or not _facade()._env_bool("MODSTORE_CREDENTIAL_TASK_GRANTS", "1"):
        return prompt, None
    grant = credential_vault.issue_task_grant(
        task_id, credential_vault.default_grant_scopes(), purpose="para_dispatch"
    )
    return _facade().insert_before_loop_context(prompt, grant.prompt_line()), grant


def _post_para_api_once(
    req: _facade().Dict[str, _facade().Any],
) -> _facade().Dict[str, _facade().Any]:
    h = _facade()
    units, check_revision, blocked = validated_check_units(req)
    if blocked is not None:
        return blocked
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
    branch = check_revision or str(req.get("branch") or "main").strip() or "main"
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
    payload_group = PreparedTaskGroup()
    options = task_payload_options(req, units)
    task_id = str(req.get("para_task_id") or "").strip()
    submission_started = False
    dispatched: list = []
    dispatch_failures: list = []
    try:
        with _facade().httpx.Client(timeout=_facade()._api_timeout(), trust_env=False) as client:
            grant_task = str(req.get("para_task_id") or req.get("request_id") or "").strip()
            token_info = _facade()._get_para_token(client, base, grant_task)
            token = token_info["token"]
            if task_id:
                final = h._wait_for_para_task(client, base, token, task_id, req)
                ok = bool(final.get("ok"))
                return {
                    "handler": "para_delegate",
                    "ok": ok,
                    "accepted": True,
                    "completed": ok,
                    "task_id": task_id,
                    "source": "para_api",
                    "status": final.get("status"),
                    "para_result": final.get("snapshot"),
                    "error": final.get("error") or "",
                    "outcome": (
                        "terminal"
                        if ok
                        or final.get("status") in {"para_task_failed", "para_task_merge_conflict"}
                        else "unknown"
                    ),
                    "requires_reconciliation": not ok
                    and final.get("status") not in {"para_task_failed", "para_task_merge_conflict"},
                    "required_subtask_ids": req.get("required_subtask_ids") or [],
                    **(req.get("execution_identity") or {}),
                }
            base_prompt, grant = _attach_credential_grant(base_prompt, grant_task)
            selection = req
            if units:
                selection = {
                    **req,
                    "raw_input": {
                        **(req.get("raw_input") or {}),
                        "max_devices": len(units),
                    },
                }
            tier, sel_devices, select_reason = _facade()._resolve_dispatch_devices(
                client, base, token, selection
            )
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
            prepare_task_group(
                req,
                sel_devices,
                base_prompt=base_prompt,
                units=units,
                check_revision=check_revision,
                options=options,
                grant=grant,
                group=payload_group,
                transform=prepare_dolt_ticket_payload,
            )
            if payload_group.blocked is not None:
                return payload_group.blocked
            # All scopes and final prompts are validated before the first child POST.
            for device, unit, selected_tool, payload in payload_group.payloads:
                device_id = str(device["id"])
                if task_id:
                    payload["task_id"] = task_id
                from modstore_server.node_coordinator import (
                    assert_incident_claim,
                    current_claim,
                )

                claim = current_claim()
                if claim:
                    assert_incident_claim(int(claim["event_id"]))
                submission_started = True
                resp = client.post(
                    f"{base}/api/tasks",
                    headers={
                        "Authorization": f"Bearer {token}",
                        "Idempotency-Key": (
                            f"{req.get('request_id') or grant_task}:{device_id}"
                            + (f":{unit['unit_id']}" if unit else "")
                        ),
                    },
                    json=payload,
                )
                body = h._safe_json(resp)
                ok = (
                    resp.status_code < 400
                    and isinstance(body, dict)
                    and bool(body.get("task") or body.get("subtask"))
                )
                if not ok:
                    dispatch_failures.append(
                        {
                            "device_id": device_id,
                            "status_code": resp.status_code,
                            "error": (
                                str(
                                    body.get("error")
                                    or body.get("detail")
                                    or "Invalid dispatch receipt"
                                )[:500]
                                if isinstance(body, dict)
                                else "Invalid dispatch receipt"
                            ),
                        }
                    )
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
                            "outcome": "unknown",
                            "requires_reconciliation": True,
                            "retryable": False,
                            "dispatch_failures": dispatch_failures,
                            "planned_devices": payload_group.planned_devices,
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
                accepted_task_id = str(accepted.get("task_id") or "").strip()
                if (
                    not accepted_task_id
                    or not accepted.get("subtask_id")
                    or (task_id and accepted_task_id != task_id)
                    or any(
                        row.get("subtask_id") == accepted.get("subtask_id") for row in dispatched
                    )
                ):
                    return {
                        "handler": "para_delegate",
                        "ok": False,
                        "accepted": bool(task_id),
                        "completed": False,
                        "status": "para_api_identity_mismatch",
                        "outcome": "unknown",
                        "requires_reconciliation": True,
                        "retryable": False,
                        "partial": True,
                        "task_id": task_id,
                        "planned_devices": payload_group.planned_devices,
                        "devices": dispatched,
                        "error": "Para dispatch returned missing or conflicting task identity",
                    }
                if not task_id:
                    task_id = accepted_task_id
                dispatched.append(
                    {
                        "device_id": device_id,
                        "device_name": accepted.get("device_name") or device.get("name"),
                        "subtask_id": accepted.get("subtask_id"),
                        "tool_name": selected_tool or h._dev_tool(),
                        **({"unit_id": unit["unit_id"]} if unit else {}),
                    }
                )
            if not dispatched:
                if grant is not None:
                    from modstore_server.cred_vault import revoke_task_grants

                    revoke_task_grants(grant.task_id, reason="para_no_subtask_created")
                return _facade()._outbox_response(
                    {**req, "para_payload": payload_group.first_payload},
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
                "planned_devices": payload_group.planned_devices,
                "required_subtask_ids": [
                    str(device["subtask_id"]) for device in dispatched if device.get("subtask_id")
                ],
                "dispatch_failures": dispatch_failures,
                "partial": bool(dispatch_failures)
                or len(dispatched) != len(payload_group.planned_devices),
                **(req.get("execution_identity") or {}),
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
            final = h._wait_for_para_task(
                client,
                base,
                token,
                task_id,
                {
                    **req,
                    "required_subtask_ids": result["required_subtask_ids"],
                    "planned_devices": result["planned_devices"],
                },
            )
            complete = bool(final.get("ok")) and not result["partial"]
            uncertain = final.get("status") not in {
                "para_task_completed",
                "para_task_merged",
                "para_task_failed",
                "para_task_merge_conflict",
            }
            return {
                **result,
                "ok": complete,
                "completed": complete,
                "status": "partial" if result["partial"] else final.get("status"),
                "outcome": "unknown" if uncertain else "terminal",
                "requires_reconciliation": uncertain,
                "retryable": False if uncertain or result["partial"] else True,
                "para_result": final.get("snapshot"),
                "error": (
                    ""
                    if complete
                    else str(final.get("error") or "Para required child dispatch incomplete")
                ),
            }
    except RECOVERABLE_ERRORS as exc:
        result = h._outbox_response(
            {
                **req,
                "para_task_id": task_id,
                "para_payload": payload_group.first_payload,
                "required_subtask_ids": [
                    str(device["subtask_id"]) for device in dispatched if device.get("subtask_id")
                ],
                "planned_devices": payload_group.planned_devices,
                "dispatch_failures": dispatch_failures,
                "replay_allowed": False,
            },
            status="para_api_failed_outboxed",
            error=f"Para API 调用失败，已写入 outbox: {str(exc)[:500]}",
        )
        result.update(
            accepted=bool(task_id),
            task_id=task_id,
            completed=False,
            outcome="unknown",
            requires_reconciliation=True,
            retryable=False,
            devices=dispatched,
            planned_devices=payload_group.planned_devices,
            dispatch_failures=dispatch_failures,
            required_subtask_ids=[
                str(device["subtask_id"]) for device in dispatched if device.get("subtask_id")
            ],
            partial=bool(payload_group.planned_devices)
            and len(dispatched) < len(payload_group.planned_devices),
            submission_started=submission_started,
            **(req.get("execution_identity") or {}),
        )
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
    if url and (req.get("raw_input") or {}).get("independent_checks"):
        return {
            "handler": "para_delegate",
            "ok": False,
            "accepted": False,
            "retryable": False,
            "status": "blocked_independent_checks",
            "error": "Explicit check groups require the Para task receipt protocol",
        }
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
        body = body if isinstance(body, dict) else {}
        accepted = body.get("accepted") is True and bool(
            body.get("task_id") or body.get("para_task_id")
        )
        completed = accepted and body.get("completed") is True and body.get("ok") is True
        ok = resp.status_code < 400 and (completed or accepted)
        return {
            "handler": "para_delegate",
            "ok": ok,
            "status_code": resp.status_code,
            "source": "para_webhook",
            "accepted": accepted,
            "completed": completed,
            "task_id": body.get("task_id") or body.get("para_task_id") or "",
            "status": (
                "para_task_completed"
                if completed
                else "para_task_accepted" if accepted else "para_webhook_unknown"
            ),
            "outcome": "terminal" if completed else "unknown",
            "requires_reconciliation": not completed,
            "retryable": False,
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
    budget = req.get("execution_budget") or {}
    limit = budget.get("context_chars")
    if limit and not req.get("para_task_id"):
        size = len(_facade()._build_para_prompt(req))
        if size > int(limit):
            return {
                "handler": "para_delegate",
                "ok": False,
                "accepted": False,
                "queued": False,
                "retryable": False,
                "status": "blocked_context_budget",
                "error": f"Execution context has {size} characters; budget allows {limit}",
                "execution_budget": budget,
                "requested_execution_budget": budget,
            }
    result = _facade()._post_webhook(req)
    if budget and isinstance(result, dict):
        result["requested_execution_budget"] = budget
    return result
