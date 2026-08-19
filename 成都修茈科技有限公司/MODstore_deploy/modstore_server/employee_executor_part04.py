# ruff: noqa
"""Implementation extracted from the public facade module."""
from __future__ import annotations
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
        except Exception:
            j = {}
        if resp.status_code == 200 and int(j.get("errcode", 0)) == 0:
            return {"handler": "wechat_notify", "status": "ok"}
        return {"handler": "wechat_notify", "status": "failed", "response": resp.text[:500]}
    except Exception as e:
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
        return {"handler": "openapi_tool", "error": "missing connector_id or operation_id"}
    try:
        connector_id_int = int(connector_id)
    except (TypeError, ValueError):
        return {"handler": "openapi_tool", "error": f"invalid connector_id: {connector_id!r}"}

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
    except Exception as exc:
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
    except Exception as e:
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
    except Exception:
        _facade().logger.warning(
            "trusted duty contract resolution failed employee_id=%s", employee_id, exc_info=True
        )
        return ({}, {})


def _action_agent_runner(
    actions_cfg: _facade().Dict[str, _facade().Any],
    reasoning: _facade().Dict[str, _facade().Any],
    task: str,
    employee_id: str,
    user_id: int,
) -> _facade().Dict[str, _facade().Any]:
    """Dispatch the ``agent`` handler by running an EmployeeAgentRunner ReAct loop.

    Reads ``actions.agent.workspace`` to determine the project root and whether
    write tools should be available.  Falls back to the reasoning text when the
    runner is unavailable.
    """
    try:
        from modstore_server.mod_employee_agent_runner import EmployeeAgentRunner
    except ImportError as exc:
        return {"handler": "agent", "ok": False, "error": f"EmployeeAgentRunner 未导入: {exc}"}
    agent_cfg = actions_cfg.get("agent") if isinstance(actions_cfg.get("agent"), dict) else {}
    ws_cfg = agent_cfg.get("workspace") if isinstance(agent_cfg.get("workspace"), dict) else {}
    cog_input = reasoning.get("input") if isinstance(reasoning.get("input"), dict) else {}
    read_only = bool(ws_cfg.get("read_only", True)) or bool(cog_input.get("burn_in_read_only"))
    requires_root = bool(ws_cfg.get("requires_project_root", False))
    project_root_raw = (
        cog_input.get("project_root")
        or cog_input.get("workspace_root")
        or (reasoning.get("input") or {}).get("project_root")
    )
    workspace_root = "."
    if not project_root_raw:
        try:
            from modstore_server.employee_workspace_manager import (
                enforce_workspace_limit,
                get_workspace_path,
            )

            _ws_path = get_workspace_path(str(employee_id or ""))
            workspace_root = str(_ws_path)
            enforce_workspace_limit(str(employee_id or ""))
        except Exception:
            pass
    if project_root_raw:
        try:
            resolved = _facade()._trusted_system_burn_in_project_root(
                project_root_raw, cog_input=cog_input, user_id=user_id, read_only=read_only
            )
            if not resolved:
                from modstore_server.integrations.vibe_adapter import ensure_within_workspace

                resolved = str(
                    ensure_within_workspace(str(project_root_raw), user_id=int(user_id or 0))
                )
            workspace_root = resolved
        except Exception as exc:
            return {"handler": "agent", "ok": False, "error": f"project_root 路径无效: {exc}"}
    elif requires_root:
        return {
            "handler": "agent",
            "ok": False,
            "error": "该员工需要项目根目录才能分析文件。请在 input_data 中提供 project_root 字段（例如：{'project_root': '/path/to/project'}）。",
        }
    sf = _facade().get_session_factory()

    async def _agent_call_llm(
        messages: _facade().List[_facade().Dict[str, _facade().Any]], **kwargs
    ) -> _facade().Dict[str, _facade().Any]:
        mt = int(kwargs.get("max_tokens") or 2048)
        provider = str(reasoning.get("provider") or "auto")
        model = str(reasoning.get("model") or "auto")
        if not reasoning.get("_bench_platform_only") and (
            provider.lower() == "auto" or model.lower() == "auto"
        ):
            uid_ai = int(user_id or 0)
            if uid_ai > 0:
                from modstore_server.mod_scaffold_runner import resolve_llm_provider_model_auto

                with sf() as sess:
                    urow = sess.query(_facade().User).filter(_facade().User.id == uid_ai).first()
                    if urow:
                        (rp, rm, perr) = await resolve_llm_provider_model_auto(
                            sess, urow, None, None
                        )
                        if rp and rm and (not perr):
                            (provider, model) = (rp, rm)
            else:
                from modstore_server.services.llm import resolve_platform_bench_llm

                (rp, rm) = resolve_platform_bench_llm()
                if rp and rm:
                    (provider, model) = (rp, rm)
        if reasoning.get("_bench_platform_only"):
            from modstore_server.services.llm import chat_dispatch_via_platform_only

            return await chat_dispatch_via_platform_only(provider, model, messages, max_tokens=mt)
        with sf() as sess:
            return await _facade().chat_dispatch_via_session(
                sess, user_id, provider, model, messages, max_tokens=mt
            )

    def _agent_http_allow_hosts() -> set[str]:
        raw = _facade().os.environ.get("MODSTORE_AGENT_HTTP_ALLOW_HOSTS", "").strip()
        if not raw:
            return set()
        return {x.strip().lower() for x in raw.split(",") if x.strip()}

    async def _allowlist_http_get(url: str, **kwargs) -> _facade().Dict[str, _facade().Any]:
        hosts = _agent_http_allow_hosts()
        if not hosts:
            return {"ok": False, "error": "未配置 MODSTORE_AGENT_HTTP_ALLOW_HOSTS"}
        try:
            parsed = _facade().urlparse(url or "")
            host = (parsed.hostname or "").lower()
        except Exception:
            return {"ok": False, "error": "无效 URL"}
        if not host or host not in hosts:
            return {"ok": False, "error": f"host 不在白名单: {host or '?'}"}
        timeout = float(kwargs.get("timeout") or 30)
        headers = kwargs.get("headers") if isinstance(kwargs.get("headers"), dict) else {}
        try:
            async with _facade().httpx.AsyncClient(timeout=timeout) as client:
                r = await client.get(url, headers=headers)
            text = (r.text or "")[:500000]
            return {"ok": r.status_code < 400, "status": r.status_code, "text": text, "error": ""}
        except Exception as exc:
            return {"ok": False, "status": 0, "text": "", "error": str(exc)[:400]}

    async def _noop_http_get(url: str, **kwargs) -> _facade().Dict[str, _facade().Any]:
        return {"ok": False, "error": "agent 模式下 HTTP 工具未启用"}

    async def _noop_http_post(url: str, **kwargs) -> _facade().Dict[str, _facade().Any]:
        return {"ok": False, "error": "agent 模式下 HTTP 工具未启用"}

    _http_get_impl = _allowlist_http_get if _agent_http_allow_hosts() else _noop_http_get
    ctx: _facade().Dict[str, _facade().Any] = {
        "call_llm": _agent_call_llm,
        "http_get": _http_get_impl,
        "http_post": _noop_http_post,
        "workspace_root": workspace_root,
        "employee_id": employee_id,
        "cli_fallback_enabled": employee_id == "llm-ops-engineer"
        and _facade().os.environ.get("MODSTORE_LLM_CLI_FALLBACK_ENABLED", "1").strip().lower()
        not in ("0", "false", "off", "disabled"),
        "read_only": read_only,
        "employee_input": dict(cog_input),
        "employee_capabilities": [
            str(item).strip() for item in agent_cfg.get("capabilities") or [] if str(item).strip()
        ],
        "research_tools_enabled": not read_only
        and _facade().os.environ.get("MODSTORE_AGENT_RESEARCH_TOOLS_ENABLED", "").strip().lower()
        in ("1", "true", "yes"),
    }
    try:
        from modstore_server.employee_scope_policy import workspace_policy_from_manifest

        with sf() as _sess:
            _pack = _facade().load_employee_pack_resolved(_sess, employee_id)
            _manifest = _pack.get("manifest") if isinstance(_pack.get("manifest"), dict) else {}
            (_sg, _fg, _ag) = workspace_policy_from_manifest(_manifest)
            ctx["scope_globs"] = _sg
            ctx["forbidden_globs"] = _fg
            ctx["approval_required_globs"] = _ag
    except Exception:
        ctx["scope_globs"] = []
        ctx["forbidden_globs"] = []
        ctx["approval_required_globs"] = []
    try:
        from modstore_server.integrations.ops_action_handlers import OPS_EMPLOYEE_IDS
        from modstore_server.integrations.ops_action_handlers import repo_root as _ops_repo_root

        if employee_id in OPS_EMPLOYEE_IDS:
            ctx["ops_readonly_repo_root"] = str(_ops_repo_root())
    except Exception:
        pass
    system_prompt = str(reasoning.get("system_prompt") or "").strip()
    if not system_prompt:
        cog_cfg = reasoning.get("cognition_cfg") or {}
        ag = cog_cfg.get("agent") if isinstance(cog_cfg.get("agent"), dict) else cog_cfg
        system_prompt = str(ag.get("system_prompt") or "").strip()
    runner = EmployeeAgentRunner(ctx, workspace_root=workspace_root)

    async def _run() -> _facade().Dict[str, _facade().Any]:
        return await runner.run(task, system_prompt=system_prompt)

    try:
        result = _facade()._run_coro_sync(_run())
    except Exception as exc:
        _facade().logger.exception("agent runner raised employee=%s", employee_id)
        return {"handler": "agent", "ok": False, "error": f"agent 执行异常: {exc}"}
    tool_calls = result.get("tool_calls") if isinstance(result.get("tool_calls"), list) else []
    cr_ids: set[int] = set()
    files_changed: _facade().List[_facade().Dict[str, _facade().Any]] = []
    for tc in tool_calls:
        if not isinstance(tc, dict):
            continue
        tool_name = str(tc.get("tool") or "").strip()
        tr = tc.get("result") if isinstance(tc.get("result"), dict) else {}
        cid_raw = tr.get("change_request_id")
        try:
            cid = int(cid_raw or 0)
        except (TypeError, ValueError):
            cid = 0
        if cid > 0:
            cr_ids.add(cid)
        cids_raw = (
            tr.get("change_request_ids") if isinstance(tr.get("change_request_ids"), list) else []
        )
        for one in cids_raw:
            try:
                _cid = int(one or 0)
            except (TypeError, ValueError):
                _cid = 0
            if _cid > 0:
                cr_ids.add(_cid)
        p = str(tr.get("path") or "").strip()
        if p and (tool_name == "write_workspace_file" or cid > 0 or bool(cids_raw)):
            item = {"path": p}
            if cid > 0:
                item["change_request_id"] = cid
            files_changed.append(item)
    return {
        "handler": "agent",
        "ok": result.get("ok", False),
        "summary": result.get("summary") or "",
        "rounds": result.get("rounds", 0),
        "tool_calls_count": len(result.get("tool_calls") or []),
        "tool_call_kinds": [
            str(tc.get("tool") or "")
            for tc in tool_calls
            if isinstance(tc, dict) and str(tc.get("tool") or "").strip()
        ][:50],
        "tool_call_success_count": sum(
            (
                1
                for tc in tool_calls
                if isinstance(tc, dict)
                and isinstance(tc.get("result"), dict)
                and (tc["result"].get("ok") is not False)
                and (not str(tc["result"].get("error") or "").strip())
            )
        ),
        "tool_call_failure_count": sum(
            (
                1
                for tc in tool_calls
                if isinstance(tc, dict)
                and isinstance(tc.get("result"), dict)
                and (
                    tc["result"].get("ok") is False
                    or bool(str(tc["result"].get("error") or "").strip())
                )
            )
        ),
        "change_request_ids": sorted(cr_ids),
        "files_changed": files_changed[:200],
        "workspace_root": workspace_root,
        "error": result.get("error") or "",
    }
