# mypy: disable-error-code="assignment, attr-defined, no-any-return, union-attr, valid-type"
# isort: skip_file
"""Implementation extracted from the public facade module."""

from __future__ import annotations

from modstore_server.operational_errors import RECOVERABLE_ERRORS
import importlib


def _facade():
    return importlib.import_module("modstore_server.employee_executor")


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
        return {
            "handler": "agent",
            "ok": False,
            "error": f"EmployeeAgentRunner 未导入: {exc}",
        }
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
        except RECOVERABLE_ERRORS:
            pass
    if project_root_raw:
        try:
            resolved = _facade()._trusted_system_burn_in_project_root(
                project_root_raw,
                cog_input=cog_input,
                user_id=user_id,
                read_only=read_only,
            )
            if not resolved:
                from modstore_server.integrations.vibe_adapter import (
                    ensure_within_workspace,
                )

                resolved = str(
                    ensure_within_workspace(str(project_root_raw), user_id=int(user_id or 0))
                )
            workspace_root = resolved
        except RECOVERABLE_ERRORS as exc:
            return {
                "handler": "agent",
                "ok": False,
                "error": f"project_root 路径无效: {exc}",
            }
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
                from modstore_server.mod_scaffold_runner import (
                    resolve_llm_provider_model_auto,
                )

                with sf() as sess:
                    urow = sess.query(_facade().User).filter(_facade().User.id == uid_ai).first()
                    if urow:
                        rp, rm, perr = await resolve_llm_provider_model_auto(sess, urow, None, None)
                        if rp and rm and (not perr):
                            provider, model = (rp, rm)
            else:
                from modstore_server.services.llm import resolve_platform_bench_llm

                rp, rm = resolve_platform_bench_llm()
                if rp and rm:
                    provider, model = (rp, rm)
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
        except RECOVERABLE_ERRORS:
            return {"ok": False, "error": "无效 URL"}
        if not host or host not in hosts:
            return {"ok": False, "error": f"host 不在白名单: {host or '?'}"}
        timeout = float(kwargs.get("timeout") or 30)
        headers = kwargs.get("headers") if isinstance(kwargs.get("headers"), dict) else {}
        try:
            async with _facade().httpx.AsyncClient(timeout=timeout) as client:
                r = await client.get(url, headers=headers)
            text = (r.text or "")[:500000]
            return {
                "ok": r.status_code < 400,
                "status": r.status_code,
                "text": text,
                "error": "",
            }
        except RECOVERABLE_ERRORS as exc:
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
            _sg, _fg, _ag = workspace_policy_from_manifest(_manifest)
            ctx["scope_globs"] = _sg
            ctx["forbidden_globs"] = _fg
            ctx["approval_required_globs"] = _ag
    except RECOVERABLE_ERRORS:
        ctx["scope_globs"] = []
        ctx["forbidden_globs"] = []
        ctx["approval_required_globs"] = []
    try:
        from modstore_server.integrations.ops_action_handlers import OPS_EMPLOYEE_IDS
        from modstore_server.integrations.ops_action_handlers import (
            repo_root as _ops_repo_root,
        )

        if employee_id in OPS_EMPLOYEE_IDS:
            ctx["ops_readonly_repo_root"] = str(_ops_repo_root())
    except RECOVERABLE_ERRORS:
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
    except RECOVERABLE_ERRORS as exc:
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
