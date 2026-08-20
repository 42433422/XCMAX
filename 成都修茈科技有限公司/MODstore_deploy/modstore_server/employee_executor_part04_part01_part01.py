# mypy: disable-error-code="arg-type, attr-defined, no-any-return, union-attr, valid-type"
# isort: skip_file
"""Implementation extracted from the public facade module."""

from __future__ import annotations

from modstore_server.operational_errors import RECOVERABLE_ERRORS
import importlib


def _facade():
    return importlib.import_module("modstore_server.employee_executor")


def _action_wechat_notify(
    actions_cfg: _facade().Dict[str, _facade().Any],
    reasoning: _facade().Dict[str, _facade().Any],
    task: str,
) -> _facade().Dict[str, _facade().Any]:
    """企业微信机器人 Webhook。"""
    wechat_cfg = actions_cfg.get("wechat_notify") or {}
    webhook_url = str(wechat_cfg.get("webhook_url") or "").strip()
    if not webhook_url:
        return {
            "handler": "wechat_notify",
            "status": "not_configured",
            "message": "未配置 actions.wechat_notify.webhook_url",
        }
    message_type = str(wechat_cfg.get("message_type") or "text").strip()
    content = str(reasoning.get("reasoning") or "")[:2048]
    payload: _facade().Dict[str, _facade().Any] = {"msgtype": message_type}
    if message_type == "markdown":
        payload["markdown"] = {"content": f"**AI 员工通知**\n任务: {task}\n\n{content}"}
    else:
        payload["text"] = {"content": f"【AI员工】任务:{task}\n{content}"}
    try:
        resp = _facade().httpx.post(webhook_url, json=payload, timeout=10.0)
        try:
            j = resp.json()
        except RECOVERABLE_ERRORS:
            j = {}
        if resp.status_code == 200 and int(j.get("errcode", 0)) == 0:
            return {"handler": "wechat_notify", "status": "ok"}
        return {
            "handler": "wechat_notify",
            "status": "failed",
            "response": resp.text[:500],
        }
    except RECOVERABLE_ERRORS as e:
        return {"handler": "wechat_notify", "status": "error", "error": str(e)}


def _action_openapi_tool(
    actions_cfg: _facade().Dict[str, _facade().Any],
    reasoning: _facade().Dict[str, _facade().Any],
    task: str,
    employee_id: str,
    user_id: int,
) -> _facade().Dict[str, _facade().Any]:
    """通过受控 OpenAPI 连接器调用第三方 API。

    配置示例（员工 actions.openapi_tool）::

        {
          "connector_id": 12,
          "operation_id": "createIssue",
          "params": {"project": "MOD"},
          "body": {"title": "{{task}}", "body": "{{reasoning}}"},
          "headers": {"X-Trace": "ai-employee"},
          "timeout": 20
        }
    """
    cfg = actions_cfg.get("openapi_tool") or {}
    connector_id = cfg.get("connector_id")
    operation_id = cfg.get("operation_id")
    if not connector_id or not operation_id:
        return {
            "handler": "openapi_tool",
            "error": "missing connector_id or operation_id",
        }
    try:
        connector_id_int = int(connector_id)
    except (TypeError, ValueError):
        return {
            "handler": "openapi_tool",
            "error": f"invalid connector_id: {connector_id!r}",
        }

    def _render(value: _facade().Any) -> _facade().Any:
        if isinstance(value, str):
            return (
                value.replace("{{reasoning}}", str(reasoning.get("reasoning") or ""))
                .replace("{{task}}", task)
                .replace("{{employee_id}}", employee_id)
            )
        if isinstance(value, dict):
            return {str(k): _render(v) for (k, v) in value.items()}
        if isinstance(value, list):
            return [_render(v) for v in value]
        return value

    try:
        from modstore_server.openapi_connector_runtime import call_generated_operation
    except RECOVERABLE_ERRORS as exc:
        return {"handler": "openapi_tool", "error": f"runtime unavailable: {exc}"}
    timeout = float(cfg.get("timeout") or 30)
    result = call_generated_operation(
        connector_id=connector_id_int,
        user_id=int(user_id or 0),
        operation_id=str(operation_id),
        params=_render(cfg.get("params") or {}),
        body=_render(cfg.get("body")) if cfg.get("body") is not None else None,
        headers=_render(cfg.get("headers") or {}),
        timeout=timeout,
        source="employee",
    )
    return {
        "handler": "openapi_tool",
        "connector_id": connector_id_int,
        "operation_id": operation_id,
        "ok": bool(result.get("ok")),
        "status_code": result.get("status_code"),
        "body": result.get("body"),
        "error": result.get("error") or "",
        "duration_ms": result.get("duration_ms"),
    }


def _tpl_str(s: str, reasoning: _facade().Dict[str, _facade().Any], task: str) -> str:
    rtxt = str((reasoning or {}).get("reasoning") or "")
    return (s or "").replace("{{reasoning}}", rtxt).replace("{{task}}", task or "")


def _tpl_obj(
    obj: _facade().Any, reasoning: _facade().Dict[str, _facade().Any], task: str
) -> _facade().Any:
    if isinstance(obj, str):
        return _facade()._tpl_str(obj, reasoning, task)
    if isinstance(obj, dict):
        return {str(k): _tpl_obj(v, reasoning, task) for (k, v) in obj.items()}
    if isinstance(obj, list):
        return [_tpl_obj(x, reasoning, task) for x in obj]
    return obj


def _action_fhd_business(
    actions_cfg: _facade().Dict[str, _facade().Any],
    reasoning: _facade().Dict[str, _facade().Any],
    task: str,
) -> _facade().Dict[str, _facade().Any]:
    biz = actions_cfg.get("fhd_business") or {}
    base = str(
        biz.get("fhd_base_url")
        or biz.get("base_url")
        or _facade().os.environ.get("FHD_BUSINESS_BASE_URL")
        or ""
    ).strip()
    path = str(biz.get("api_path") or biz.get("path") or "").strip().lstrip("/")
    method = str(biz.get("method") or "POST").strip().upper()
    if not base:
        return {"handler": "fhd_business", "error": "missing fhd_base_url"}
    if not path:
        return {"handler": "fhd_business", "error": "missing api_path"}
    raw_body = biz.get("body")
    body: _facade().Dict[str, _facade().Any] = {}
    if isinstance(raw_body, dict):
        tb = _facade()._tpl_obj(raw_body, reasoning, task)
        body = tb if isinstance(tb, dict) else {}
    headers_in = biz.get("headers") if isinstance(biz.get("headers"), dict) else {}
    hdrs = {str(k): _facade()._tpl_str(str(v), reasoning, task) for (k, v) in headers_in.items()}
    key = str(
        biz.get("business_key") or _facade().os.environ.get("FHD_BUSINESS_API_KEY") or ""
    ).strip()
    if key:
        hdrs.setdefault("X-FHD-Business-Key", key)
    url = f"{base.rstrip('/')}/api/business/{path}"
    try:
        timeout = float(biz.get("timeout") or 30.0)
        resp = _facade().httpx.request(
            method, url, json=body or None, headers=hdrs, timeout=timeout
        )
        return {
            "handler": "fhd_business",
            "url": url,
            "status_code": resp.status_code,
            "response": (resp.text or "")[:2000],
        }
    except RECOVERABLE_ERRORS as e:
        return {"handler": "fhd_business", "error": str(e), "url": url}


def _merge_original_input_into_reasoning(
    reasoning: _facade().Dict[str, _facade().Any],
    original_input: _facade().Dict[str, _facade().Any],
) -> _facade().Dict[str, _facade().Any]:
    """Backfill action-critical input fields without overwriting cognition output."""
    out = dict(reasoning or {})
    current_input = out.get("input") if isinstance(out.get("input"), dict) else {}
    merged_input = dict(current_input)
    for key in (
        "project_root",
        "workspace_root",
        "allow_medium_risk",
        "allow_high_risk",
        "priority",
        "handler",
        "handler_mode",
        "delegate",
        "multi_step",
        "fallback_cursor",
        "burn_in_read_only",
        "suppress_employee_im",
        "suppress_handoff",
        "suppress_change_requests",
        "im_reply_managed",
        "_trusted_duty_contract_execution",
        "base_url",
        "fhd_base",
        "xcemp_path",
    ):
        if key in original_input and key not in merged_input:
            merged_input[key] = original_input[key]
    out["input"] = merged_input
    return out


def _trusted_system_burn_in_project_root(
    project_root: _facade().Any,
    *,
    cog_input: _facade().Dict[str, _facade().Any],
    user_id: int,
    read_only: bool,
) -> str:
    """Allow system identity to use the configured monorepo root.

    Normal agent runs remain tenant-workspace scoped. Trusted exceptions:

    - read-only burn-in / duty observation (``burn_in_read_only`` or
      ``_trusted_duty_contract_execution`` + ``read_only``)
    - system incident-team / duty write under monorepo
      (``_trusted_incident_team_execution`` or write-capable trusted duty)

    Paths must resolve under ``XCMAX_MONOREPO_ROOT`` (symlink/``..`` safe).
    """
    if int(user_id or 0) > 0:
        return ""
    trusted_duty_execution = cog_input.get("_trusted_duty_contract_execution") is True
    trusted_incident_team = cog_input.get("_trusted_incident_team_execution") is True
    burn_in = cog_input.get("burn_in_read_only") is True
    allow_read = read_only and (burn_in or trusted_duty_execution)
    allow_write = trusted_incident_team or (trusted_duty_execution and (not read_only))
    if not (allow_read or allow_write):
        return ""
    configured = str(
        _facade().os.environ.get("XCMAX_MONOREPO_ROOT")
        or _facade().os.environ.get("MODSTORE_DUTY_PROJECT_ROOT")
        or _facade().os.environ.get("MODSTORE_REPO_ROOT")
        or ""
    ).strip()
    if not configured:
        return ""
    trusted_root = _facade().Path(configured).expanduser().resolve()
    candidate = _facade().Path(str(project_root or "")).expanduser().resolve()
    try:
        candidate.relative_to(trusted_root)
    except ValueError:
        return ""
    if not trusted_root.is_dir() or not candidate.is_dir():
        return ""
    return str(candidate)


def _trusted_system_duty_contract_execution(
    employee_id: str, payload: _facade().Dict[str, _facade().Any], *, user_id: int
) -> tuple[_facade().Dict[str, _facade().Any], _facade().Dict[str, _facade().Any]]:
    """Resolve the reviewed duty runtime for a verified system trigger.

    Catalog archives are customer/store delivery artifacts and can lag the
    reviewed duty source.  System schedule/event execution may use that source
    only when every caller-provided contract field matches the contract SSOT.
    High-risk roles remain on the existing approval/veto path.
    """
    if int(user_id or 0) > 0 or not isinstance(payload, dict):
        return ({}, {})
    trigger = str(payload.get("trigger") or "").strip().lower()
    if trigger not in {"schedule", "event"}:
        return ({}, {})
    if str(payload.get("schedule_source") or "").strip() != "duty_work_contract":
        return ({}, {})
    provided = payload.get("work_contract")
    if (
        not isinstance(provided, dict)
        or str(provided.get("schema") or "").strip() != "xcagi.duty_employee_work_contracts/v1"
    ):
        return ({}, {})
    try:
        from modstore_server.duty_workforce_contracts import (
            load_reviewed_duty_manifest,
            workforce_contract_map,
        )

        contract = workforce_contract_map().get(str(employee_id or "").strip()) or {}
        risk = str(contract.get("risk_level") or "").strip().lower()
        if risk not in {"low", "medium"}:
            return ({}, {})
        contract_trigger = (
            contract.get("trigger") if isinstance(contract.get("trigger"), dict) else {}
        )
        if trigger == "schedule" and (not str(contract_trigger.get("cron") or "").strip()):
            return ({}, {})
        if trigger == "event":
            event_type = str(payload.get("event_type") or "").strip()
            source = str(payload.get("source") or "").strip()
            allowed_events = {
                str(item or "").strip() for item in contract_trigger.get("events") or []
            }
            if not event_type or not (
                event_type in allowed_events
                or (source and f"{event_type}:{source}" in allowed_events)
            ):
                return ({}, {})
        expected_acceptance = [str(item) for item in contract.get("acceptance") or []]
        provided_acceptance = [str(item) for item in provided.get("acceptance") or []]
        if (
            str(provided.get("mode") or "").strip() != str(contract.get("mode") or "").strip()
            or str(provided.get("risk_level") or "").strip().lower() != risk
            or provided_acceptance != expected_acceptance
        ):
            return ({}, {})
        return (dict(contract), load_reviewed_duty_manifest(employee_id))
    except RECOVERABLE_ERRORS:
        _facade().logger.warning(
            "trusted duty contract resolution failed employee_id=%s",
            employee_id,
            exc_info=True,
        )
        return ({}, {})
