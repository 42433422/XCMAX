# mypy: disable-error-code="valid-type, attr-defined, no-any-return"
"""Behavior mixin extracted from the public facade class."""

from __future__ import annotations

import importlib

from modstore_server.operational_errors import RECOVERABLE_ERRORS


def _facade():
    return importlib.import_module("modstore_server.mod_employee_agent_runner")


class _EmployeeAgentRunnerPart01Mixin:
    def __init__(
        self,
        ctx: _facade().Dict[str, _facade().Any],
        *,
        max_rounds: _facade().Optional[int] = None,
        workspace_root: _facade().Optional[str] = None,
    ) -> None:
        self.ctx = ctx
        self.max_rounds = (
            _facade()._default_max_rounds() if max_rounds is None else max(1, min(10, max_rounds))
        )
        self.workspace_root = workspace_root or str(ctx.get("workspace_root") or ".")

    async def run(
        self,
        task: str,
        *,
        system_prompt: str = "",
        extra_history: _facade().Optional[_facade().List[_facade().Dict[str, str]]] = None,
    ) -> _facade().Dict[str, _facade().Any]:
        """Execute *task* using the ReAct loop.

        Returns::

            {
              "ok": bool,
              "summary": str,          # final answer or error message
              "rounds": int,           # number of LLM calls made
              "tool_calls": [...],     # list of {tool, input, result}
              "error": str | None,
            }
        """
        read_only = bool(self.ctx.get("read_only"))
        protocol = (
            _facade().READ_ONLY_TOOL_PROTOCOL_HEADER
            if read_only
            else _facade().TOOL_PROTOCOL_HEADER
        ).format(max_rounds=self.max_rounds)
        if self.ctx.get("research_tools_enabled") and (not read_only):
            protocol = protocol.rstrip() + _facade().RESEARCH_TOOLS_APPEND
        if str(self.ctx.get("employee_id") or "").strip() == "llm-ops-engineer":
            protocol = protocol.rstrip() + (
                _facade().LLM_OPS_READ_ONLY_TOOLS_APPEND
                if read_only
                else _facade().LLM_OPS_TOOLS_APPEND
            )
        capabilities = {
            str(item).strip()
            for item in self.ctx.get("employee_capabilities") or []
            if str(item).strip()
        }
        if not read_only and "host_probe" in capabilities:
            protocol = protocol.rstrip() + _facade().HOST_CHECKER_TOOLS_APPEND
        if not read_only and "xcemp_validate" in capabilities:
            protocol = protocol.rstrip() + _facade().SELF_CHECKER_TOOLS_APPEND
        messages: _facade().List[_facade().Dict[str, str]] = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt.strip()})
        messages.append({"role": "system", "content": protocol})
        for msg in extra_history or []:
            messages.append(msg)
        messages.append(
            {
                "role": "user",
                "content": f"{task.strip()}\n\n（工作区根目录：{self.workspace_root}，可通过 read_workspace_file 等工具访问）",
            }
        )
        tool_calls_log: _facade().List[_facade().Dict[str, _facade().Any]] = []
        for round_n in range(self.max_rounds):
            resp = await self._call_llm(messages)
            if not resp.get("ok"):
                return {
                    "ok": False,
                    "summary": resp.get("error") or "LLM 调用失败",
                    "rounds": round_n,
                    "tool_calls": tool_calls_log,
                    "error": resp.get("error"),
                }
            raw = resp["content"].strip()
            messages.append({"role": "assistant", "content": raw})
            parsed = _facade()._try_parse_json(raw)
            if parsed is not None and "answer" in parsed:
                return {
                    "ok": True,
                    "summary": str(parsed["answer"]),
                    "rounds": round_n + 1,
                    "tool_calls": tool_calls_log,
                    "error": None,
                }
            if parsed is None or "tool" not in parsed:
                return {
                    "ok": True,
                    "summary": raw,
                    "rounds": round_n + 1,
                    "tool_calls": tool_calls_log,
                    "error": None,
                }
            tool_name = str(parsed.get("tool") or "")
            tool_input = parsed.get("input") or {}
            _facade().logger.info(
                "[agent:%s] round=%d tool=%s input_keys=%s",
                self.ctx.get("employee_id", "?"),
                round_n + 1,
                tool_name,
                list(tool_input.keys())[:6],
            )
            result = await self._dispatch_tool(tool_name, tool_input)
            tool_calls_log.append({"tool": tool_name, "input": tool_input, "result": result})
            messages.append(
                {
                    "role": "user",
                    "content": _facade().json.dumps({"tool_result": result}, ensure_ascii=False),
                }
            )
        messages.append(
            {
                "role": "user",
                "content": '已达到最大工具调用轮次，请根据目前的结果给出最终答案。输出格式：{"thought":"...", "answer":"..."}',
            }
        )
        resp = await self._call_llm(messages, max_tokens=1500)
        parsed = _facade()._try_parse_json(resp.get("content") or "") if resp.get("ok") else None
        final = (
            (parsed or {}).get("answer")
            or resp.get("content")
            or "已达到最大轮次，请查看工具调用日志"
        )
        return {
            "ok": True,
            "summary": str(final),
            "rounds": self.max_rounds,
            "tool_calls": tool_calls_log,
            "error": None,
        }

    async def _dispatch_tool(
        self, name: str, input_data: _facade().Dict[str, _facade().Any]
    ) -> _facade().Dict[str, _facade().Any]:
        try:
            if self.ctx.get("read_only") and name not in _facade()._READ_ONLY_AGENT_TOOLS:
                return {
                    "ok": False,
                    "blocked": True,
                    "error": f"只读运行模式禁止工具：{name or '?'}",
                }
            employee_id = str(self.ctx.get("employee_id") or "").strip()
            capabilities = {
                str(item).strip()
                for item in self.ctx.get("employee_capabilities") or []
                if str(item).strip()
            }
            if name == "probe_mod_host":
                if "host_probe" not in capabilities or employee_id != "host-checker":
                    return {
                        "ok": False,
                        "error": f"员工 {employee_id or '?'} 无权使用 {name}",
                    }
                from modstore_server.employee_specialized_tools import (
                    configured_host_probe_allowlist,
                    probe_mod_host,
                )

                employee_input = (
                    self.ctx.get("employee_input")
                    if isinstance(self.ctx.get("employee_input"), dict)
                    else {}
                )
                base_url = str(
                    input_data.get("base_url")
                    or employee_input.get("base_url")
                    or employee_input.get("fhd_base")
                    or _facade().os.environ.get("FHD_BASE_URL")
                    or ""
                ).strip()
                if not base_url:
                    return {"ok": False, "error": "缺少 base_url 且未配置 FHD_BASE_URL"}
                return await probe_mod_host(
                    base_url,
                    allowed_hosts=configured_host_probe_allowlist(),
                    timeout_seconds=float(input_data.get("timeout_seconds") or 10.0),
                )
            if name == "validate_xcemp_package":
                if "xcemp_validate" not in capabilities or employee_id != "self-checker":
                    return {
                        "ok": False,
                        "error": f"员工 {employee_id or '?'} 无权使用 {name}",
                    }
                from modstore_server.employee_specialized_tools import (
                    validate_xcemp_package,
                )

                employee_input = (
                    self.ctx.get("employee_input")
                    if isinstance(self.ctx.get("employee_input"), dict)
                    else {}
                )
                relative_path = str(
                    input_data.get("xcemp_path") or employee_input.get("xcemp_path") or ""
                ).strip()
                return await validate_xcemp_package(
                    self.workspace_root,
                    relative_path,
                    timeout_seconds=float(input_data.get("timeout_seconds") or 20.0),
                )
            llm_ops_tools = {
                "list_platform_llm_models",
                "list_llm_cli_status",
                "list_available_ai_routes",
                "get_platform_llm_quota",
                "get_platform_llm_route",
                "get_llm_route_autopilot",
                "run_llm_route_autopilot",
                "switch_platform_llm_route",
                "rollback_platform_llm_route",
            }
            if name in llm_ops_tools and employee_id != "llm-ops-engineer":
                return {
                    "ok": False,
                    "error": f"员工 {employee_id or '?'} 无权使用 {name}",
                }
            if name == "list_platform_llm_models":
                from modstore_server.llm_runtime_route import platform_model_catalog

                return await platform_model_catalog(
                    str(input_data.get("provider") or "") or None,
                    refresh=bool(input_data.get("refresh", False))
                    and (not bool(self.ctx.get("read_only"))),
                )
            if name == "list_llm_cli_status":
                from modstore_server.llm_cli_fallback import cli_status_catalog

                return await cli_status_catalog(
                    live_probe=bool(input_data.get("live_probe", False))
                    and (not bool(self.ctx.get("read_only")))
                )
            if name == "list_available_ai_routes":
                from modstore_server.llm_ai_assets import build_ai_asset_inventory
                from modstore_server.llm_cli_fallback import cli_status_catalog
                from modstore_server.llm_quota_monitor import platform_quota_snapshot
                from modstore_server.llm_runtime_route import platform_model_catalog

                platform, cli = await _facade().asyncio.gather(
                    platform_model_catalog(
                        refresh=bool(input_data.get("refresh", False))
                        and (not bool(self.ctx.get("read_only")))
                    ),
                    cli_status_catalog(
                        live_probe=bool(input_data.get("live_cli_probe", False))
                        and (not bool(self.ctx.get("read_only")))
                    ),
                )
                quota = await platform_quota_snapshot(
                    live_probe=bool(input_data.get("live_quota_probe", False))
                    and (not bool(self.ctx.get("read_only"))),
                    catalog=platform,
                )
                assets = build_ai_asset_inventory(platform, cli, quota)
                return {
                    "ok": bool(
                        platform.get("ok")
                        and cli.get("ok")
                        and quota.get("ok")
                        and assets.get("ok")
                    ),
                    "platform": platform,
                    "quota": quota,
                    "cli_fallback": cli,
                    "assets": assets,
                    "policy": "platform_api_first_then_local_cli",
                }
            if name == "get_platform_llm_route":
                from modstore_server.llm_runtime_route import (
                    read_runtime_route_state,
                    rollback_target,
                )
                from modstore_server.services.llm import resolve_platform_bench_llm

                provider, model = resolve_platform_bench_llm()
                return {
                    "ok": True,
                    "scope": "platform_ai_employees",
                    "state": read_runtime_route_state(),
                    "effective": {"provider": provider, "model": model},
                    "rollback": rollback_target(),
                }
            if name == "get_platform_llm_quota":
                from modstore_server.llm_quota_monitor import platform_quota_snapshot

                return await platform_quota_snapshot(
                    live_probe=bool(input_data.get("live_probe", False))
                    and (not bool(self.ctx.get("read_only")))
                )
            if name == "get_llm_route_autopilot":
                from modstore_server.llm_runtime_autopilot import autopilot_status

                return autopilot_status()
            if name == "run_llm_route_autopilot":
                from modstore_server.llm_runtime_autopilot import (
                    reconcile_llm_route_autopilot,
                )

                return await reconcile_llm_route_autopilot(
                    triggered_by=str(input_data.get("reason") or "employee:llm-ops-engineer"),
                    force=False,
                )
            if name == "switch_platform_llm_route":
                from modstore_server.llm_runtime_route import switch_runtime_route

                return await switch_runtime_route(
                    str(input_data.get("provider") or ""),
                    str(input_data.get("model") or ""),
                    actor="employee:llm-ops-engineer",
                    reason=str(input_data.get("reason") or "active model switch"),
                    refresh_catalog=bool(input_data.get("refresh", False)),
                    force=False,
                )
            if name == "rollback_platform_llm_route":
                from modstore_server.llm_runtime_route import rollback_runtime_route

                return await rollback_runtime_route(
                    actor="employee:llm-ops-engineer",
                    reason=str(input_data.get("reason") or "employee requested rollback"),
                    force=False,
                )
            wr = self.workspace_root
            if name == "read_workspace_file":
                path = str(input_data.get("path") or "")
                return await _facade().tool_read_workspace_file(wr, path, self.ctx)
            if name == "write_workspace_file":
                path = str(input_data.get("path") or "")
                content = str(input_data.get("content") or "")
                return await _facade().tool_write_workspace_file(wr, path, content, self.ctx)
            if name == "list_workspace_dir":
                path = str(input_data.get("path") or ".")
                return await _facade().tool_list_workspace_dir(wr, path)
            if name == "scan_project_tree":
                path = str(input_data.get("path") or ".")
                max_files = int(input_data.get("max_files") or 200)
                return await _facade().tool_scan_project_tree(wr, path, max_files=max_files)
            if name == "identify_file_types":
                path = str(input_data.get("path") or ".")
                return await _facade().tool_identify_file_types(wr, path)
            if name == "analyze_project_summary":
                path = str(input_data.get("path") or ".")
                return await _facade().tool_analyze_project_summary(wr, path)
            if name == "run_sandboxed_python":
                code = str(input_data.get("code") or "")
                return await _facade().tool_run_sandboxed_python(code)
            if name == "http_get":
                fn = self.ctx.get("http_get")
                if not callable(fn):
                    return {"ok": False, "error": "ctx.http_get 未注入"}
                url = str(input_data.get("url") or "")
                headers = input_data.get("headers") or {}
                return await fn(url, headers=headers)
            if name == "http_post":
                fn = self.ctx.get("http_post")
                if not callable(fn):
                    return {"ok": False, "error": "ctx.http_post 未注入"}
                url = str(input_data.get("url") or "")
                body = input_data.get("json_body") or input_data.get("body") or {}
                return await fn(url, json_body=body)
            if name == "internet_search":
                if not self.ctx.get("research_tools_enabled"):
                    return {
                        "ok": False,
                        "error": "联网检索工具未启用（MODSTORE_AGENT_RESEARCH_TOOLS_ENABLED）",
                    }
                from modstore_server.research_tools import internet_search_tool

                q = str(input_data.get("query") or "")
                mr = int(input_data.get("max_results") or 8)
                return await internet_search_tool(q, max_results=max(1, min(mr, 12)))
            if name == "github_repo_snapshot":
                if not self.ctx.get("research_tools_enabled"):
                    return {
                        "ok": False,
                        "error": "GitHub 工具未启用（MODSTORE_AGENT_RESEARCH_TOOLS_ENABLED）",
                    }
                from modstore_server.research_tools import github_repo_snapshot_tool

                return await github_repo_snapshot_tool(
                    str(input_data.get("owner") or ""),
                    str(input_data.get("repo") or ""),
                )
            if name == "call_llm":
                messages = input_data.get("messages") or []
                return await self._call_llm(messages)
            return {"ok": False, "error": f"未知工具：{name!r}"}
        except RECOVERABLE_ERRORS as exc:
            _facade().logger.exception("agent tool dispatch error tool=%s", name)
            return {"ok": False, "error": str(exc)[:300]}

    async def _call_llm(
        self,
        messages: _facade().List[_facade().Dict[str, str]],
        *,
        max_tokens: int = 2048,
        temperature: float = 0.2,
    ) -> _facade().Dict[str, _facade().Any]:
        fn = self.ctx.get("call_llm")
        if not callable(fn):
            primary = {"ok": False, "content": "", "error": "ctx.call_llm 未注入"}
            return await self._maybe_cli_fallback(messages, primary)
        try:
            primary = await _facade().asyncio.wait_for(
                fn(messages, max_tokens=max_tokens, temperature=temperature),
                timeout=_facade()._llm_timeout_seconds(),
            )
            if primary.get("ok"):
                return primary
            return await self._maybe_cli_fallback(messages, primary)
        except _facade().asyncio.TimeoutError:
            timeout_s = int(_facade()._llm_timeout_seconds())
            primary = {
                "ok": False,
                "content": "",
                "error": f"LLM 调用超时（{timeout_s}s）",
            }
            return await self._maybe_cli_fallback(messages, primary)
        except RECOVERABLE_ERRORS as exc:
            primary = {"ok": False, "content": "", "error": str(exc)[:300]}
            return await self._maybe_cli_fallback(messages, primary)

    async def _maybe_cli_fallback(
        self,
        messages: _facade().List[_facade().Dict[str, str]],
        primary: _facade().Dict[str, _facade().Any],
    ) -> _facade().Dict[str, _facade().Any]:
        employee_id = str(self.ctx.get("employee_id") or "").strip()
        if employee_id != "llm-ops-engineer" or not bool(
            self.ctx.get("cli_fallback_enabled", False)
        ):
            return primary
        from modstore_server.llm_cli_fallback import chat_via_cli_fallback

        fallback = await chat_via_cli_fallback(
            messages, timeout=min(180.0, max(30.0, _facade()._llm_timeout_seconds()))
        )
        fallback["primary_error"] = str(primary.get("error") or "upstream_failed")[:300]
        return fallback
