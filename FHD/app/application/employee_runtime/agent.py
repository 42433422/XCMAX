"""EmployeeAgent：真正员工运行时编排对象。

把此前散落在 ``executor.execute_employee_task_local`` 的流程收敛为一个对象，并补齐：
- 记忆召回（短期会话 + 长期向量）→ 注入 system_prompt
- 行动后记忆回写
- 为 agent handler 注入「作用域工具 + gate」钩子（P1 填充 tool_scope / workspace_guard）
- 感知层钩子（P2 填充 PerceptionPipeline）

执行链：风险门 → 感知 → 记忆召回 → 认知（单轮补全）→ 行动（agent 走多轮工具循环）→ 记忆回写。
返回结构与历史 ``execute_employee_task_local`` 完全一致，保证所有调用方兼容。
"""

from __future__ import annotations

import logging
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.application.employee_runtime import executor as _ex
from app.application.employee_runtime.loader import (
    build_employee_context,
    load_employee_pack_from_disk,
    parse_employee_config_v2,
    resolve_pack_dir,
)
from app.application.employee_runtime.memory import EmployeeMemoryManager, MemoryContext
from app.application.employee_runtime.risk_gate import gate_action_or_block
from app.domain.employee.memory_scope import MemoryScope
from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)


class EmployeeAgent:
    """单个已安装 employee_pack 的运行时实例。"""

    def __init__(self, employee_id: str) -> None:
        self.employee_id = str(employee_id or "").strip()

    # ---- 钩子：子阶段在后续 Phase 增强（P1 tool_scope/guard、P2 perception） ----
    def _build_agent_tools(
        self, manifest: dict[str, Any], config: dict[str, Any]
    ) -> list[dict[str, Any]] | None:
        """返回 agent handler 可用的工具子集；None 表示用 agent_loop 默认工具。"""
        try:
            from app.application.employee_runtime.tool_scope import resolve_employee_tools

            return resolve_employee_tools(self.employee_id, manifest, config)
        except ImportError:
            return None
        except RECOVERABLE_ERRORS:
            logger.debug("build agent tools fallback emp=%s", self.employee_id, exc_info=True)
            return None

    def _build_agent_gate(
        self,
        manifest: dict[str, Any],
        config: dict[str, Any],
        workspace_root: str | None,
        input_data: dict[str, Any] | None = None,
    ) -> Any:
        """返回 (tool_name, args) -> {ok, reason} 的 gate；None 表示无额外门控。"""
        ws_gate = None
        write_gate = None
        try:
            from app.application.employee_runtime.workspace_guard import build_employee_gate

            ws_gate = build_employee_gate(self.employee_id, manifest, config, workspace_root)
        except ImportError:
            pass
        except RECOVERABLE_ERRORS:
            logger.debug("build workspace gate fallback emp=%s", self.employee_id, exc_info=True)
        try:
            from app.application.employee_runtime.write_approval import build_write_approval_gate

            write_gate = build_write_approval_gate(self.employee_id, input_data)
        except ImportError:
            pass
        except RECOVERABLE_ERRORS:
            logger.debug("build write gate fallback emp=%s", self.employee_id, exc_info=True)
        try:
            from app.application.employee_runtime.write_approval import compose_gates

            return compose_gates(ws_gate, write_gate)
        except ImportError:
            return ws_gate or write_gate

    def _run_upstream_collaboration(
        self,
        task: str,
        payload: dict[str, Any],
        manifest: dict[str, Any],
        config: dict[str, Any],
    ) -> dict[str, Any] | None:
        if payload.get("skip_collaboration"):
            return None
        try:
            from app.application.employee_runtime.metrics import record_orchestration
            from app.application.employee_runtime.orchestrator import EmployeeOrchestrator

            orch = EmployeeOrchestrator()
            deps = orch.depends_on(self.employee_id, manifest, config)
            if not deps:
                return None
            record_orchestration(self.employee_id)
            return orch.run_upstream(
                self.employee_id,
                task,
                manifest=manifest,
                config=config,
                runtime_context={
                    "task": task,
                    "employee_id": self.employee_id,
                    "user_id": payload.get("user_id"),
                    "workspace_root": payload.get("workspace_root"),
                    "session_id": payload.get("session_id"),
                },
            )
        except ImportError:
            return None
        except RECOVERABLE_ERRORS:
            logger.debug("upstream collaboration skipped emp=%s", self.employee_id, exc_info=True)
            return None

    def _perceive(self, config: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
        try:
            from app.application.employee_runtime.perception import PerceptionPipeline

            return PerceptionPipeline(config).process(payload)
        except ImportError:
            return _ex._perception_real(config, payload)
        except RECOVERABLE_ERRORS:
            logger.debug("perception fallback emp=%s", self.employee_id, exc_info=True)
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
    ) -> dict[str, Any]:
        employee_id = self.employee_id
        t0 = time.perf_counter()
        payload = dict(input_data or {})
        if workspace_root and "workspace_root" not in payload:
            payload["workspace_root"] = workspace_root
        logger.info(
            "employee_agent_run employee_id=%s task_len=%s session=%s",
            employee_id,
            len(task or ""),
            session_id or "-",
        )
        try:
            pack = load_employee_pack_from_disk(employee_id)
            manifest = pack.get("manifest") or {}
            pack_root = Path(str(pack.get("pack_dir") or resolve_pack_dir(employee_id) or ""))
            config = parse_employee_config_v2(manifest)
            actions_cfg = _ex._normalize_actions_cfg(config)
            handler_list = _ex._handler_list(actions_cfg)
            upstream: dict[str, Any] | None = None

            gate = gate_action_or_block(employee_id, manifest, handler_list, payload)
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

            upstream = self._run_upstream_collaboration(task, payload, manifest, config)
            if upstream and upstream.get("node_outputs"):
                payload["upstream_outputs"] = upstream["node_outputs"]
                payload["collaboration"] = {
                    "plan_id": upstream.get("plan_id"),
                    "success": upstream.get("success"),
                    "node_results": upstream.get("node_results"),
                }

            scope = MemoryScope.from_config(employee_id, config)
            memory_mgr = EmployeeMemoryManager(scope)
            mem_ctx = memory_mgr.recall(task, user_id=user_id, session_id=session_id)
            config = self._augment_config_with_memory(config, mem_ctx)

            build_employee_context(employee_id, payload)
            perceived = self._perceive(config, payload)

            file_path_fast = str(payload.get("file_path") or payload.get("path") or "").strip()
            direct_only = handler_list == ["direct_python"] and bool(file_path_fast)
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
                reasoning = _ex._cognition_fhd(config, perceived, memory, task)
                if reasoning.get("error") and handler_list != ["direct_python"]:
                    if self._is_interactive_chat_payload(payload):
                        from app.application.employee_runtime.metrics import record_employee_run

                        record_employee_run(employee_id, success=True, task=task)
                        return self._interactive_chat_fallback_result(
                            pack,
                            manifest,
                            task,
                            handler_list,
                            reasoning,
                            t0,
                        )
                    return self._cognition_failed_result(pack, task, handler_list, reasoning, t0)

            agent_tools = (
                self._build_agent_tools(manifest, config) if "agent" in handler_list else None
            )
            agent_gate = (
                self._build_agent_gate(manifest, config, workspace_root, payload)
                if "agent" in handler_list
                else None
            )
            result = _ex._actions_fhd(
                config,
                reasoning,
                task,
                employee_id,
                pack_root,
                payload.get("workspace_root") or workspace_root,
                agent_tools=agent_tools,
                agent_gate=agent_gate,
            )
            duration_ms = round((time.perf_counter() - t0) * 1000, 3)
            ok = _ex._handlers_execution_ok(result)

            from app.application.employee_runtime.metrics import record_employee_run

            record_employee_run(
                employee_id,
                success=ok,
                task=task,
                summary=self._summarize(result),
            )
            if not ok:
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
                "collaboration_upstream": upstream
                if upstream and not upstream.get("skipped")
                else None,
            }
        except RECOVERABLE_ERRORS as exc:
            duration_ms = round((time.perf_counter() - t0) * 1000, 3)
            logger.exception("employee_agent_run failed employee_id=%s", employee_id)
            return {
                "employee_id": employee_id,
                "duration_ms": duration_ms,
                "success": False,
                "error": str(exc)[:800],
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
        return {
            "employee_id": self.employee_id,
            "pack": {"id": pack["pack_id"], "version": pack.get("version")},
            "duration_ms": round((time.perf_counter() - t0) * 1000, 3),
            "result": {
                "task": task,
                "handlers": handler_list,
                "outputs": [],
                "summary": "blocked by risk middleware",
                "risk_gate": gate,
            },
            "executed_at": datetime.now(UTC).isoformat(),
            "blocked_by_risk_gate": True,
            "success": False,
        }

    def _cognition_failed_result(
        self,
        pack: dict[str, Any],
        task: str,
        handler_list: list[str],
        reasoning: dict[str, Any],
        t0: float,
    ) -> dict[str, Any]:
        return {
            "employee_id": self.employee_id,
            "pack": {"id": pack["pack_id"], "version": pack.get("version")},
            "duration_ms": round((time.perf_counter() - t0) * 1000, 3),
            "success": False,
            "result": {
                "task": task,
                "handlers": handler_list,
                "outputs": [],
                "summary": "cognition failed",
                "cognition_error": reasoning.get("error"),
            },
            "executed_at": datetime.now(UTC).isoformat(),
        }

    @staticmethod
    def _is_interactive_chat_payload(payload: dict[str, Any]) -> bool:
        mode = str(payload.get("invoke_mode") or payload.get("mode") or "").strip().lower()
        source = str(payload.get("source") or payload.get("client_surface") or "").strip().lower()
        return mode in {"interactive_chat", "chat", "dialog"} and source in {
            "admin_im",
            "mobile_im",
            "employee_im",
            "admin_console",
            "mobile_app",
        }

    def _interactive_chat_fallback_result(
        self,
        pack: dict[str, Any],
        manifest: dict[str, Any],
        task: str,
        handler_list: list[str],
        reasoning: dict[str, Any],
        t0: float,
    ) -> dict[str, Any]:
        employee_meta = (
            manifest.get("employee") if isinstance(manifest.get("employee"), dict) else {}
        )
        label = str(
            manifest.get("name")
            or employee_meta.get("label")
            or pack.get("pack_id")
            or self.employee_id
        ).strip()
        text = (
            f"我在，{label} 已接到消息。当前员工认知模型暂不可用，"
            "所以先进入降级对话；你可以继续补充明确任务，涉及写库、改文件或高风险动作仍会走风险门和审批。"
        )
        return {
            "employee_id": self.employee_id,
            "pack": {"id": pack["pack_id"], "version": pack.get("version")},
            "duration_ms": round((time.perf_counter() - t0) * 1000, 3),
            "success": True,
            "result": {
                "task": task,
                "handlers": handler_list,
                "outputs": [
                    {
                        "handler": "interactive_chat_fallback",
                        "ok": True,
                        "output": text,
                    }
                ],
                "summary": "interactive chat fallback",
                "cognition_error": reasoning.get("error"),
            },
            "executed_at": datetime.now(UTC).isoformat(),
            "source": "employee_runtime.local",
            "degraded": True,
        }


__all__ = ["EmployeeAgent"]
