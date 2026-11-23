"""员工运行时：风险、感知、记忆、认知与行动；agent 工具和授权解析失败时拒绝执行。"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.application.employee_runtime import executor as _ex
from app.application.employee_runtime.chat_results import (
    build_collaboration_context_result,
    build_interactive_chat_fallback_result,
    build_interactive_chat_reply_result,
    is_collaboration_context_payload,
    is_interactive_chat_payload,
)
from app.application.employee_runtime.loader import (
    build_employee_context,
    load_employee_pack_from_disk,
    parse_employee_config_v2,
    resolve_pack_dir,
)
from app.application.employee_runtime.memory import EmployeeMemoryManager, MemoryContext
from app.application.employee_runtime.office_workers import (
    is_deterministic_office_worker,
)
from app.application.employee_runtime.result_builders import (
    build_blocked_result,
    build_cognition_failed_result,
)
from app.application.employee_runtime.result_verifier import pending_employee_result
from app.application.employee_runtime.risk_gate import gate_action_or_block
from app.domain.employee.memory_scope import MemoryScope
from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)


def _employee_gate_contract(
    manifest: dict[str, Any],
    config: dict[str, Any],
    tools: list[dict[str, Any]],
) -> str:
    from app.infrastructure.codex.binding import canonical_digest

    return canonical_digest({"manifest": manifest, "config": config, "tools": tools})


class EmployeeAgent:
    """单个已安装 employee_pack 的运行时实例。"""

    def __init__(self, employee_id: str) -> None:
        self.employee_id = str(employee_id or "").strip()

    # ---- 钩子：子阶段在后续 Phase 增强（P1 tool_scope/guard、P2 perception） ----
    def _build_agent_tools(
        self, manifest: dict[str, Any], config: dict[str, Any]
    ) -> list[dict[str, Any]]:
        """工具解析失败时拒绝全部工具。"""
        try:
            from app.application.employee_runtime.tool_scope import (
                resolve_employee_tools,
            )

            return resolve_employee_tools(self.employee_id, manifest, config)
        except RECOVERABLE_ERRORS:
            logger.debug("build agent tools denied", exc_info=True)
            return []

    def _build_agent_gate(
        self,
        manifest: dict[str, Any],
        config: dict[str, Any],
        workspace_root: str | None,
        runtime_context: dict[str, Any] | None = None,
    ) -> Any:
        """Keep employee file policy; durable child tasks own business approvals."""
        try:
            from app.application.employee_runtime.workspace_guard import (
                build_employee_gate,
            )

            return build_employee_gate(self.employee_id, manifest, config, workspace_root)
        except RECOVERABLE_ERRORS:
            logger.exception("employee authorization initialization failed closed")
            return lambda name, args: {
                "ok": False,
                "reason": "工具授权初始化失败，未执行",
            }

    def _run_upstream_collaboration(
        self,
        task: str,
        payload: dict[str, Any],
        manifest: dict[str, Any],
        config: dict[str, Any],
        runtime_context: dict[str, Any] | None = None,
        authenticated_user_id: int = 0,
    ) -> dict[str, Any] | None:
        if (runtime_context or {}).get("employee_collaboration_skip") is True:
            return None
        try:
            from app.application.employee_runtime.metrics import record_orchestration
            from app.application.employee_runtime.orchestrator import (
                EmployeeOrchestrator,
            )

            orch = EmployeeOrchestrator()
            deps = orch.depends_on(self.employee_id, manifest, config)
            if not deps:
                return None
            record_orchestration(self.employee_id)
            trusted = dict(runtime_context or {})
            try:
                trusted_user_id = int(trusted.get("user_id") or 0)
            except (TypeError, ValueError):
                trusted_user_id = 0
            trusted.update(
                task=task,
                employee_id=self.employee_id,
                user_id=trusted_user_id if trusted_user_id > 0 else authenticated_user_id,
                workspace_root=trusted.get("workspace_root") or payload.get("workspace_root"),
                session_id=trusted.get("session_id") or payload.get("session_id"),
            )
            return orch.run_upstream(
                self.employee_id,
                task,
                manifest=manifest,
                config=config,
                runtime_context=trusted,
            )
        except ImportError:
            logger.exception("employee collaboration runtime unavailable")
            return {
                "skipped": False,
                "success": False,
                "error_code": "employee_collaboration_unavailable",
                "message": "声明的上游员工协作不可用，已阻止当前员工继续执行",
            }
        except RECOVERABLE_ERRORS:
            logger.exception("required employee collaboration failed")
            return {
                "skipped": False,
                "success": False,
                "error_code": "employee_collaboration_failed",
                "message": "声明的上游员工协作失败，已阻止当前员工继续执行",
            }

    def _perceive(self, config: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
        try:
            from app.application.employee_runtime.perception import PerceptionPipeline

            return PerceptionPipeline(config).process(payload)
        except ImportError:
            return _ex._perception_real(config, payload)
        except RECOVERABLE_ERRORS:
            logger.debug("perception fallback", exc_info=True)
            return _ex._perception_real(config, payload)

    # ---- 系统提示词注入记忆 ----
    @staticmethod
    def _augment_config_with_memory(
        config: dict[str, Any], mem_ctx: MemoryContext
    ) -> dict[str, Any]:
        suffix = mem_ctx.as_system_suffix()
        if not suffix:
            return config
        import copy

        new_cfg = copy.deepcopy(config)
        cog = new_cfg.get("cognition")
        if not isinstance(cog, dict):
            cog = {}
            new_cfg["cognition"] = cog
        agent = cog.get("agent")
        if not isinstance(agent, dict):
            agent = {}
            cog["agent"] = agent
        base = str(agent.get("system_prompt") or "")
        agent["system_prompt"] = (base + "\n\n" + suffix) if base else suffix
        return new_cfg

    @staticmethod
    def _augment_config_with_persona(config: dict[str, Any], user_id: int) -> dict[str, Any]:
        """按 SSOT(小C+平台员工共享 Persona)给员工 system_prompt 附加用户人格风格段。

        只取「怎么说话」(四轴风格),保留员工自身岗位身份。fail-safe:无风格则原样返回。
        """
        from app.application.persona_style_inject import persona_style_for_user

        style = persona_style_for_user(user_id)
        if not style:
            return config
        import copy

        new_cfg = copy.deepcopy(config)
        cog = new_cfg.get("cognition")
        if not isinstance(cog, dict):
            cog = {}
            new_cfg["cognition"] = cog
        agent = cog.get("agent")
        if not isinstance(agent, dict):
            agent = {}
            cog["agent"] = agent
        base = str(agent.get("system_prompt") or "")
        suffix = "对当前用户的沟通风格：" + style
        agent["system_prompt"] = (base + "\n\n" + suffix) if base else suffix
        return new_cfg

    @staticmethod
    def _summarize(result: dict[str, Any]) -> str:
        outputs = result.get("outputs") if isinstance(result, dict) else None
        if not isinstance(outputs, list):
            return str(result.get("summary") or "") if isinstance(result, dict) else ""
        parts: list[str] = []
        for out in outputs:
            if not isinstance(out, dict):
                continue
            text = out.get("output") or out.get("summary") or out.get("error") or ""
            if text:
                parts.append(f"[{out.get('handler', '?')}] {str(text)[:300]}")
        return " | ".join(parts)[:1200]

    # ---- 主入口 ----
    def run(
        self,
        task: str,
        input_data: dict[str, Any] | None = None,
        *,
        user_id: int = 0,
        workspace_root: str | None = None,
        session_id: str | None = None,
        runtime_context: dict[str, Any] | None = None,
        on_event: Callable[[dict[str, Any]], Any] | None = None,
    ) -> dict[str, Any]:
        employee_id = self.employee_id
        t0 = time.perf_counter()
        payload = dict(input_data or {})
        payload.pop("workspace_root", None)
        trusted_context = dict(runtime_context or {})
        if user_id:
            trusted_context.setdefault("user_id", user_id)
        if session_id:
            trusted_context.setdefault("session_id", session_id)
        for key in (
            "invoke_mode",
            "mode",
            "source",
            "client_surface",
            "root_employee_id",
            "upstream_outputs",
            "skip_collaboration",
        ):
            payload.pop(key, None)
        for key in ("invoke_mode", "source", "client_surface"):
            if trusted_context.get(key):
                payload[key] = trusted_context[key]
        if trusted_context.get("employee_collaboration_run") is True:
            outputs = trusted_context.get("node_outputs")
            payload.update(
                invoke_mode="collaboration_context",
                source="employee_collaboration",
                client_surface="employee_runtime",
                root_employee_id=str(trusted_context.get("employee_id") or employee_id),
                upstream_outputs=dict(outputs) if isinstance(outputs, dict) else {},
                skip_collaboration=True,
            )
        elif trusted_context.get("employee_collaboration_skip") is True:
            payload["skip_collaboration"] = True
        if workspace_root:
            payload["workspace_root"] = workspace_root
        from app.application.employee_runtime.task_continuity import maybe_continue_employee_task

        routed = maybe_continue_employee_task(
            employee_id,
            task,
            payload,
            user_id=user_id,
            session_id=session_id,
            workspace_root=workspace_root,
            runtime_context=trusted_context,
        )
        if routed is not None:
            return routed
        logger.info("employee_agent_run task_len=%s", len(task or ""))
        try:
            pack = load_employee_pack_from_disk(employee_id)
            manifest = pack.get("manifest") or {}
            from app.mod_sdk.product_plane import employee_execution_block_reason

            boundary_reason = employee_execution_block_reason(employee_id, manifest)
            if boundary_reason:
                return {
                    "employee_id": employee_id,
                    "pack": {"id": pack["pack_id"], "version": pack.get("version")},
                    "duration_ms": round((time.perf_counter() - t0) * 1000, 3),
                    "success": False,
                    "blocked_by_product_plane": True,
                    "error": boundary_reason,
                    "error_code": "control_plane_employee_not_available",
                    "retryable": False,
                    "executed_at": datetime.now(UTC).isoformat(),
                }
            pack_root = Path(str(pack.get("pack_dir") or resolve_pack_dir(employee_id) or ""))
            config = parse_employee_config_v2(manifest)
            declared_config = deepcopy(config)
            actions_cfg = _ex._normalize_actions_cfg(config)
            handler_list = _ex._handler_list(actions_cfg)
            upstream: dict[str, Any] | None = None

            gate = gate_action_or_block(employee_id, manifest, handler_list, trusted_context)
            if not gate.get("ok"):
                from app.application.employee_runtime.metrics import record_employee_run

                record_employee_run(
                    employee_id,
                    success=False,
                    blocked=True,
                    task=task,
                    summary=str(gate.get("reason") or gate.get("message") or ""),
                )
                return self._blocked_result(pack, task, handler_list, gate, t0)

            if not is_interactive_chat_payload(payload) and not is_collaboration_context_payload(
                payload
            ):
                upstream = self._run_upstream_collaboration(
                    task,
                    payload,
                    manifest,
                    config,
                    trusted_context,
                    authenticated_user_id=user_id,
                )
            if upstream and upstream.get("success") is False:
                from app.application.employee_runtime.metrics import record_employee_run

                message = str(upstream.get("message") or "上游员工协作未完成，当前员工未执行")
                record_employee_run(
                    employee_id,
                    success=False,
                    blocked=True,
                    task=task,
                    summary=message,
                )
                return {
                    "employee_id": employee_id,
                    "duration_ms": round((time.perf_counter() - t0) * 1000, 3),
                    "success": False,
                    "error_code": str(
                        upstream.get("error_code") or "employee_collaboration_failed"
                    ),
                    "error": message,
                    "collaboration": upstream,
                    "executed_at": datetime.now(UTC).isoformat(),
                }
            if upstream and upstream.get("node_outputs"):
                payload["upstream_outputs"] = upstream["node_outputs"]
                payload["collaboration"] = {
                    "plan_id": upstream.get("plan_id"),
                    "success": upstream.get("success"),
                    "node_results": upstream.get("node_results"),
                }

            from app.infrastructure.tenant_scope import current_tenant_id

            tenant = current_tenant_id()
            declared_tenant = trusted_context.get("tenant_id")
            if tenant is None:
                tenant = declared_tenant
            elif declared_tenant is not None and str(declared_tenant) != str(tenant):
                # Do not read or write memory if trusted runtime scopes conflict.
                tenant = None
            declared_actor = trusted_context.get("local_user_id") or trusted_context.get("user_id")
            if declared_actor is not None and str(declared_actor) != str(user_id):
                tenant = None
            scope = MemoryScope.from_config(employee_id, config, tenant_id=tenant)
            memory_mgr = EmployeeMemoryManager(
                scope,
                provenance={
                    **{
                        key: trusted_context[key]
                        for key in (
                            "run_id",
                            "agent_run_id",
                            "employee_run_id",
                            "task_id",
                            "node_id",
                        )
                        if key in trusted_context
                    },
                    "pack_id": pack.get("pack_id"),
                    "pack_version": pack.get("version"),
                },
            )
            mem_ctx = memory_mgr.recall(task, user_id=user_id, session_id=session_id)
            config = self._augment_config_with_memory(config, mem_ctx)
            config = self._augment_config_with_persona(config, user_id)

            build_employee_context(employee_id, payload)
            perceived = self._perceive(config, payload)

            selected_runtime = None
            defer_cognition = False
            if "agent" in handler_list and not (
                is_interactive_chat_payload(payload) or is_collaboration_context_payload(payload)
            ):
                from app.infrastructure.codex import policy

                try:
                    selected_runtime = policy.runtime_settings()
                    if (
                        selected_runtime.engine != "codex"
                        or "employee" not in selected_runtime.surfaces
                    ):
                        raise policy.RuntimePolicyError("员工 Agent 必须启用固定 Codex 执行器")
                except policy.RuntimePolicyError:
                    return self._cognition_failed_result(
                        pack,
                        task,
                        handler_list,
                        {
                            "error": "员工运行时配置无效",
                            "error_code": "runtime_configuration_invalid",
                            "retryable": False,
                        },
                        t0,
                    )
                defer_cognition = True
                if handler_list != ["agent"]:
                    return self._cognition_failed_result(
                        pack,
                        task,
                        handler_list,
                        {
                            "error": "Codex 员工入口暂不支持混合执行器配置",
                            "error_code": "employee_runtime_handlers_unsupported",
                            "retryable": False,
                        },
                        t0,
                    )

            file_path_fast = str(payload.get("file_path") or payload.get("path") or "").strip()
            direct_only = handler_list == ["direct_python"] and (
                bool(file_path_fast) or is_deterministic_office_worker(employee_id, handler_list)
            )
            if direct_only:
                reasoning: dict[str, Any] = {
                    "input": dict(payload),
                    "reasoning": "",
                    "skipped_cognition": True,
                    **{
                        k: payload[k] for k in ("file_path", "path", "user_request") if k in payload
                    },
                }
            else:
                memory = _ex._memory_light({"employee_id": employee_id})
                reasoning = (
                    _ex._cognition_fhd(config, perceived, memory, task, defer_to_runtime=True)
                    if defer_cognition
                    else _ex._cognition_fhd(config, perceived, memory, task)
                )
                if reasoning.get("error") and is_collaboration_context_payload(payload):
                    from app.application.employee_runtime.metrics import (
                        record_employee_run,
                    )

                    result = build_collaboration_context_result(
                        self.employee_id,
                        pack,
                        manifest,
                        task,
                        handler_list,
                        reasoning,
                        t0,
                        mem_ctx,
                        degraded=True,
                    )
                    record_employee_run(
                        employee_id,
                        success=True,
                        task=task,
                        summary=self._summarize(result["result"]),
                    )
                    return result
                if reasoning.get("error") and handler_list != ["direct_python"]:
                    if is_interactive_chat_payload(payload):
                        from app.application.employee_runtime.metrics import (
                            record_employee_run,
                        )

                        record_employee_run(employee_id, success=True, task=task)
                        return build_interactive_chat_fallback_result(
                            self.employee_id,
                            pack,
                            manifest,
                            task,
                            handler_list,
                            reasoning,
                            t0,
                        )
                    return self._cognition_failed_result(pack, task, handler_list, reasoning, t0)

            if is_collaboration_context_payload(payload):
                from app.application.employee_runtime.metrics import record_employee_run

                result = build_collaboration_context_result(
                    self.employee_id,
                    pack,
                    manifest,
                    task,
                    handler_list,
                    reasoning,
                    t0,
                    mem_ctx,
                )
                record_employee_run(
                    employee_id,
                    success=True,
                    task=task,
                    summary=self._summarize(result["result"]),
                )
                return result

            if is_interactive_chat_payload(payload):
                from app.application.employee_runtime.metrics import record_employee_run

                chat_result = build_interactive_chat_reply_result(
                    self.employee_id,
                    pack,
                    manifest,
                    task,
                    handler_list,
                    reasoning,
                    t0,
                    upstream,
                    mem_ctx,
                )
                summary = self._summarize(chat_result["result"])
                record_employee_run(employee_id, success=True, task=task, summary=summary)
                memory_mgr.remember(
                    task,
                    summary,
                    user_id=user_id,
                    session_id=session_id,
                    success=True,
                )
                return chat_result

            agent_tools = (
                self._build_agent_tools(manifest, config) if "agent" in handler_list else None
            )
            agent_gate = (
                self._build_agent_gate(manifest, config, workspace_root, trusted_context)
                if "agent" in handler_list
                else None
            )
            if defer_cognition:
                trusted_context["_employee_gate_contract"] = _employee_gate_contract(
                    manifest,
                    declared_config,
                    agent_tools or [],
                )
            result = _ex._actions_fhd(
                config,
                reasoning,
                task,
                employee_id,
                pack_root,
                workspace_root,
                agent_tools=agent_tools,
                agent_gate=agent_gate,
                runtime_context=trusted_context,
                on_event=on_event,
                settings=selected_runtime,
            )
            duration_ms = round((time.perf_counter() - t0) * 1000, 3)
            ok = _ex._handlers_execution_ok(result)
            pending = pending_employee_result(result)

            from app.application.employee_runtime.metrics import record_employee_run

            record_employee_run(
                employee_id,
                success=ok,
                task=task,
                summary=self._summarize(result),
                execution_state=str(pending.get("execution_state") or ""),
            )
            if not ok and not pending:
                try:
                    from app.application.employee_runtime.triggers import (
                        publish_employee_task_failed,
                    )

                    publish_employee_task_failed(
                        employee_id,
                        task=task,
                        message=self._summarize(result),
                        extra={"session_id": session_id, "duration_ms": duration_ms},
                    )
                except RECOVERABLE_ERRORS:
                    logger.debug("publish task failed event skipped", exc_info=True)

            if not pending:
                memory_mgr.remember(
                    task,
                    self._summarize(result),
                    user_id=user_id,
                    session_id=session_id,
                    success=ok,
                )
            return {
                "employee_id": employee_id,
                "pack": {"id": pack["pack_id"], "version": pack.get("version")},
                "duration_ms": duration_ms,
                "success": ok,
                "result": result,
                "executed_at": datetime.now(UTC).isoformat(),
                "source": "employee_runtime.local",
                "memory_used": mem_ctx.has_content,
                "collaboration_upstream": (
                    upstream if upstream and not upstream.get("skipped") else None
                ),
                **pending,
            }
        except RECOVERABLE_ERRORS:
            duration_ms = round((time.perf_counter() - t0) * 1000, 3)
            logger.exception("employee_agent_run failed")
            return {
                "employee_id": employee_id,
                "duration_ms": duration_ms,
                "success": False,
                "error": "员工运行失败，请查看服务日志",
                "executed_at": datetime.now(UTC).isoformat(),
            }

    # ---- 结果构造（与历史结构一致） ----
    def _blocked_result(
        self,
        pack: dict[str, Any],
        task: str,
        handler_list: list[str],
        gate: dict[str, Any],
        t0: float,
    ) -> dict[str, Any]:
        return build_blocked_result(self.employee_id, pack, task, handler_list, gate, t0)

    def _cognition_failed_result(
        self,
        pack: dict[str, Any],
        task: str,
        handler_list: list[str],
        reasoning: dict[str, Any],
        t0: float,
    ) -> dict[str, Any]:
        return build_cognition_failed_result(
            self.employee_id, pack, task, handler_list, reasoning, t0
        )


def restore_codex_employee_gate(
    employee_id: str,
    original_runtime_context: dict[str, Any],
    *,
    input_data: dict[str, Any] | None = None,
) -> tuple[list[str], Callable[[str, str, dict[str, Any]], dict[str, Any]]]:
    """Rebuild a gate only from the original host-owned employee binding.

    The caller must provide persisted context/input, never the resume body's
    fields. A changed pack or tool schema requires a new authorization; this
    helper cannot silently widen an existing run's permissions.
    """
    from app.application.employee_runtime.agent_runner import _codex_employee_tool_scope
    from app.mod_sdk.product_plane import employee_execution_block_reason

    if not employee_id or original_runtime_context.get("employee_id") != employee_id:
        raise ValueError("原员工运行绑定不一致")
    expected = original_runtime_context.get("_employee_gate_contract")
    if not isinstance(expected, str) or not expected:
        raise ValueError("原员工工具授权契约缺失，不能恢复")
    pack = load_employee_pack_from_disk(employee_id)
    manifest = pack.get("manifest") or {}
    if employee_execution_block_reason(employee_id, manifest):
        raise ValueError("原员工当前不可执行")
    config = parse_employee_config_v2(manifest)
    employee = EmployeeAgent(employee_id)
    tools = employee._build_agent_tools(manifest, config)
    if _employee_gate_contract(manifest, config, tools) != expected:
        raise ValueError("原员工配置或工具授权契约已变化，不能恢复")
    workspace = original_runtime_context.get("workspace_root")
    if workspace is not None and not isinstance(workspace, str):
        raise ValueError("原员工工作空间绑定无效")
    gate = employee._build_agent_gate(manifest, config, workspace, input_data)
    if gate is None:
        raise ValueError("原员工工具授权门未恢复")
    return _codex_employee_tool_scope(tools, gate)


__all__ = ["EmployeeAgent", "restore_codex_employee_gate"]
